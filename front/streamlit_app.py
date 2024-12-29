import os
import datetime
import streamlit as st
import pandas as pd
import plotly.graph_objs as go
from streamlit_plotly_events import plotly_events

from extraction.excel_extractor import (
    read_xlsx_and_return_df,
    read_xlsx_from_folder
)
from analytics.calculations import (
    import_data_with_duplicates_management,
    calculate_base_load,
)
from db.database import get_engine, create_tables, get_session, ConsumptionRecord, get_or_create_settings


# -------------------------------------------------------------------
# Nouvelle fonction utilitaire : calcul du prix en tenant compte HP/HC
# -------------------------------------------------------------------
def compute_cost_hp_hc(df, hp_cost, hc_cost, hp_start, hp_end):
    """
    Calcule le coût total selon que chaque enregistrement tombe en HP ou HC.
    df doit avoir un index 'start_time' (de type datetime) et une col 'consumption_kwh'.
    hp_cost : tarif en heures pleines
    hc_cost : tarif en heures creuses
    hp_start, hp_end : heures (datetime.time) indiquant la plage HP.

    Hypothèse : si start_time est entre hp_start et hp_end -> HP, sinon HC.
    """
    total_cost = 0.0

    for ts, row in df.iterrows():
        time = ts.time()
        if hp_start < hp_end:
            in_hp = (time >= hp_start) and (time < hp_end)
        else:
            # Plage nocturne, ex. 22:59 -> 7:42
            in_hp = (time >= hp_start) or (time < hp_end)

        cost = row['consumption_kwh'] * (hp_cost if in_hp else hc_cost)
        total_cost += cost

    return total_cost


def main():
    st.title("Suivi de consommation d'électricité")

    # Base de données et session
    engine = get_engine()
    create_tables(engine)  # Assure que la table existe
    session = get_session(engine)
    settings = get_or_create_settings(session)


# -------------------------------------------------------------------
    # Paramètres dans la sidebar collapsable
    # -------------------------------------------------------------------
    with st.sidebar:
        st.header("Paramètres")
        st.subheader("Tarifs")
        hp_cost = st.number_input(
            "Tarif heures pleines (€ / kWh)",
            value=settings.hp_cost,
            min_value=0.0,
            format="%.4f"
        )
        hc_cost = st.number_input(
            "Tarif heures creuses (€ / kWh)",
            value=settings.hc_cost,
            min_value=0.0,
            format="%.4f"
        )

        st.subheader("Plages horaires")
        hp_start = st.time_input(
            "Début HP",
            value=settings.hp_start
        )
        hp_end = st.time_input(
            "Fin HP",
            value=settings.hp_end
        )

        if st.button("Sauvegarder les paramètres"):
            # Mettre à jour les paramètres en base
            settings.hp_cost = hp_cost
            settings.hc_cost = hc_cost
            settings.hp_start = hp_start
            settings.hp_end = hp_end
            session.commit()
            st.success("Paramètres sauvegardés avec succès.")

    # -------------------------------------------------------------------
    # Import de données
    # -------------------------------------------------------------------
    st.header("Import de données")

    uploaded_files = st.file_uploader(
        "Choisissez un ou plusieurs fichiers Excel",
        type=["xlsx"],
        accept_multiple_files=True
    )

    if uploaded_files:
        if st.button("Importer les fichiers"):
            total_conflicts = []
            for uploaded_file in uploaded_files:
                df = read_xlsx_and_return_df(uploaded_file, skip_rows=15, sheet_index=1)

                st.write(f"**Fichier** : {uploaded_file.name}")
                st.write("Aperçu :", df.head())

                conflicts = import_data_with_duplicates_management(df, session)
                if conflicts:
                    st.warning(f"Conflits détectés dans le fichier {uploaded_file.name}.")
                    total_conflicts.extend([(uploaded_file.name, c) for c in conflicts])
                else:
                    st.success(f"Import terminé pour {uploaded_file.name} (pas de conflits).")

            if total_conflicts:
                st.warning("Des conflits ont été détectés sur plusieurs fichiers.")
                for file_name, conflict in total_conflicts:
                    st.write(f"**Fichier**: {file_name}")
                    handle_conflict_block(conflict, session)

    st.markdown("---")

    # -------------------------------------------------------------------
    # Calcul du talon
    # -------------------------------------------------------------------
    if st.button("Calculer le talon de consommation (global)"):
        base_load = calculate_base_load(session)
        st.write(f"Talon de consommation estimé : **{base_load:.2f} kW**")

    # -------------------------------------------------------------------
    # Visualisation (Plotly)
    # -------------------------------------------------------------------
    st.subheader("Visualisation de la consommation")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Date de début", datetime.date(2024, 1, 1))
    with col2:
        end_date = st.date_input("Date de fin", datetime.date(2024, 12, 31))

    pas_options = ["Brut (30 min)", "Horaire", "Journalier"]
    selected_pas = st.selectbox("Agrégation / pas de temps", pas_options)

    if st.button("Afficher le graphique (Plotly)"):
        start_dt = datetime.datetime.combine(start_date, datetime.time(0, 0, 0))
        end_dt = datetime.datetime.combine(end_date, datetime.time(23, 59, 59))

        # Requêter la base
        records = session.query(ConsumptionRecord).filter(
            ConsumptionRecord.start_time >= start_dt,
            ConsumptionRecord.start_time <= end_dt
        ).order_by(ConsumptionRecord.start_time).all()

        data = {
            'start_time': [r.start_time for r in records],
            'consumption_kwh': [r.consumption_kwh for r in records]
        }
        df_records = pd.DataFrame(data)
        df_records.set_index('start_time', inplace=True)

        # Agrégation
        if selected_pas == "Horaire":
            df_agg = df_records.resample('H').sum()
        elif selected_pas == "Journalier":
            df_agg = df_records.resample('D').sum()
        else:
            df_agg = df_records

        fig = go.Figure()
        if not df_agg.empty:
            x = df_agg.index
            y = df_agg['consumption_kwh']

            fig.add_trace(go.Scatter(
                x=x,
                y=y,
                mode='lines+markers',
                name='Consommation'
            ))

            base_load = calculate_base_load(session)

            fig.add_hline(
                y=base_load,
                line_dash="dash",
                annotation_text=f"Talon = {base_load:.2f}",
                annotation_position="top left",
                line_color="red"
            )

            if not y.empty:
                max_index = y.idxmax()
                max_val = y[max_index]
                fig.add_trace(go.Scatter(
                    x=[max_index],
                    y=[max_val],
                    mode='markers+text',
                    text=[f"Max: {max_val:.2f}"],
                    textposition="top center",
                    marker=dict(color="orange", size=10),
                    name='Max'
                ))

            fig.update_layout(
                title="Courbe de consommation électrique",
                xaxis_title="Date et Heure",
                yaxis_title="Consommation (kWh)",
                hovermode="x unified"
            )

            st.plotly_chart(fig, use_container_width=True)

            # Calcul HP/HC
            total_cost = compute_cost_hp_hc(df_agg, hp_cost, hc_cost, hp_start, hp_end)
            st.write(f"Consommation totale : **{df_agg['consumption_kwh'].sum():.2f} kWh**")
            st.write(f"Coût estimé (HP/HC) : **{total_cost:.2f} €**")

        else:
            st.warning("Aucune donnée à afficher dans cette période.")


def handle_conflict_block(conflict, session):
    """
    Affiche un bloc de conflit et propose la résolution simple.
    """
    col1, col2 = st.columns([2, 1])
    with col1:
        st.write(
            f"- Intervalle : [{conflict['start_time']} - {conflict['end_time']}]"
            f" | existant={conflict['existing_value']:.3f}, nouveau={conflict['new_value']:.3f}"
        )
    with col2:
        choice = st.selectbox(
            "Quelle valeur conserver ?",
            ["Existante", "Nouvelle", "Ignorer"],
            key=f"{conflict['start_time']}-{conflict['end_time']}"
        )
        if st.button("Valider", key=f"validate-{conflict['start_time']}-{conflict['end_time']}"):
            if choice == "Nouvelle":
                rec = session.query(ConsumptionRecord).filter(
                    ConsumptionRecord.start_time == conflict['start_time'],
                    ConsumptionRecord.end_time == conflict['end_time']
                ).one_or_none()
                if rec:
                    rec.consumption_kwh = conflict['new_value']
                    session.commit()
                    st.success("Valeur mise à jour avec la nouvelle consommation.")
            elif choice == "Existante":
                st.info("Valeur existante conservée.")
            else:
                st.info("Conflit ignoré (pas de modification).")


if __name__ == "__main__":
    main()
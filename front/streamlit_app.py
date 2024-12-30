import streamlit as st
from extraction.excel_extractor import read_xlsx_and_return_df
from analytics.calculations import (
    import_data_with_duplicates_management,
    calculate_base_load
)
from analytics.weather_to_consumption import integrate_weather_with_consumption
from db.database import get_engine, create_tables, get_session, get_or_create_settings
from db.database import ConsumptionRecord

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


def main():
    st.title("Ingestion & Paramètres (Streamlit)")

    # Setup DB
    engine = get_engine()
    create_tables(engine)
    session = get_session(engine)

    # Récupérer ou initialiser les Settings
    settings = get_or_create_settings(session)

    # --- Sidebar Paramètres ---
    with st.sidebar:
        st.header("Paramètres HP/HC")
        hp_cost = st.number_input("Tarif Heures Pleines (€ / kWh)", value=settings.hp_cost, min_value=0.0, format="%.4f")
        hc_cost = st.number_input("Tarif Heures Creuses (€ / kWh)", value=settings.hc_cost, min_value=0.0, format="%.4f")

        hp_start = st.time_input("Début HP", value=settings.hp_start)
        hp_end = st.time_input("Fin HP", value=settings.hp_end)

        st.header("Localisation")
        latitude = st.number_input("Latitude", value=settings.latitude, format="%.6f")
        longitude = st.number_input("Longitude", value=settings.longitude, format="%.6f")

        st.header("Photovoltaïque")
        solar_wc = st.number_input("Watt crète (Wc)", value=settings.solar_wc, format="%.0f")
        solar_efficiency = st.number_input("Efficacité", value=settings.solar_efficiency,format="%.2f")
        solar_cost = st.number_input("Coût", value=settings.solar_cost, format="%.2f")

        if st.button("Sauvegarder paramètres"):
            settings.hp_cost = hp_cost
            settings.hc_cost = hc_cost
            settings.hp_start = hp_start
            settings.hp_end = hp_end
            settings.latitude = latitude
            settings.longitude = longitude
            settings.solar_wc = solar_wc
            settings.solar_efficiency = solar_efficiency
            settings.solar_cost = solar_cost
            session.commit()
            st.success("Paramètres sauvegardés !")

    st.markdown("---")
    st.subheader("Import de données Excel")

    files = st.file_uploader("Choisissez un ou plusieurs fichiers .xlsx", type=["xlsx"], accept_multiple_files=True)
    if files:
        if st.button("Importer ces fichiers"):
            total_conflicts = []
            for f in files:
                df = read_xlsx_and_return_df(f, skip_rows=15, sheet_index=1)
                st.write(f"Fichier importé : {f.name}")
                st.write(df.head())

                conflicts = import_data_with_duplicates_management(df, session)
                if conflicts:
                    st.warning(f"Conflits détectés dans {f.name}")
                    total_conflicts.extend([(f.name, c) for c in conflicts])
                else:
                    st.success(f"Import réussi pour {f.name}")

            if total_conflicts:
                st.warning("Des conflits existent sur plusieurs fichiers.")
                for file_name, conflict in total_conflicts:
                    st.write(f"**Fichier** : {file_name}")
                    handle_conflict_block(conflict, session)

    st.markdown("---")
    st.subheader("Récupération des données météos")
    if st.button("Importer les données météo"):
        integrate_weather_with_consumption(session, settings.latitude, settings.longitude)
        st.success("Données météo importées et associées aux jours de consommation.")

    st.markdown("---")
    st.subheader("Calcul du talon (global)")

    if st.button("Calculer talon global"):
        b_load = calculate_base_load(session)
        st.write(f"Talon estimé : {b_load:.2f} kW")

    st.markdown("---")
    st.write("Pour la visualisation avancée, rendez-vous sur [Dash](http://localhost:8050) par exemple.")


if __name__ == "__main__":
    main()
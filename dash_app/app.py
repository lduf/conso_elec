import uuid

import dash
from dash import dcc, html, Input, Output
import plotly.graph_objs as go
import pandas as pd
import datetime
import dash_bootstrap_components as dbc

from db.database import get_engine, get_session, ConsumptionRecord, Weather, get_or_create_settings
from analytics.metrics import compute_talon_on_df

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.FLATLY])
app.title = "Visualisation interactive - Dash"

METEO_VARIABLES = {
    "temperature_2m": "Température (°C)",
    "precipitation": "Précipitations (mm)",
    "cloud_cover": "Couverture nuageuse (%)",
    "shortwave_radiation": "Rayonnement solaire (W/m²)",
    "direct_radiation": "Rayonnement direct (W/m²)",
    "wind_speed_10m": "Vitesse du vent (m/s)"
}

# -------------- FONCTIONS UTILES --------------

def compute_solar_production(df: pd.DataFrame, settings) -> pd.Series:
    """Production solaire (kWh)."""
    if "shortwave_radiation" not in df.columns:
        return pd.Series(0, index=df.index)
    wc = settings.solar_wc / 1000
    efficiency = settings.solar_efficiency / 100
    solar_production = (df["shortwave_radiation"] * wc * efficiency ) / 1000
    return solar_production


def compute_hp_hc_values(df: pd.DataFrame, col: str) -> tuple[float, float, float]:
    """
    Retourne (val_HP, val_HC, val_total) pour la colonne `col` dans `df`,
    en se basant sur df["is_hp"] == True/False.
    """
    if df.empty or col not in df.columns or "is_hp" not in df.columns:
        return (0.0, 0.0, 0.0)
    hp_val = df.loc[df["is_hp"] == True, col].sum()
    hc_val = df.loc[df["is_hp"] == False, col].sum()
    total_val = df[col].sum()
    return (hp_val, hc_val, total_val)


def compute_cost_hp_hc(df: pd.DataFrame, settings) -> tuple[float, float, float]:
    """
    Calcule le coût HP, HC, Total pour la consommation 'consumption_kwh' SANS PV.
    """
    if df.empty:
        return (0.0, 0.0, 0.0)
    hp_val, hc_val, _ = compute_hp_hc_values(df, "consumption_kwh")
    cost_hp = hp_val * settings.hp_cost
    cost_hc = hc_val * settings.hc_cost
    return cost_hp, cost_hc, cost_hp + cost_hc


def compute_cost_with_pv_hp_hc(df: pd.DataFrame, settings) -> tuple[float, float, float]:
    """
    Calcule le coût HP, HC, et Total en tenant compte de la production PV.
    Pour chaque point : net = max(consommation - production, 0).
    """
    if df.empty:
        return (0.0, 0.0, 0.0)
    df_calc = df.copy()
    df_calc["net_conso"] = df_calc["consumption_kwh"] - df_calc["solar_production"]
    df_calc.loc[df_calc["net_conso"] < 0, "net_conso"] = 0

    hp_val = df_calc.loc[df_calc["is_hp"] == True, "net_conso"].sum()
    hc_val = df_calc.loc[df_calc["is_hp"] == False, "net_conso"].sum()
    cost_hp = hp_val * settings.hp_cost
    cost_hc = hc_val * settings.hc_cost
    return cost_hp, cost_hc, cost_hp + cost_hc


def compute_solar_loss_hp_hc(df: pd.DataFrame) -> tuple[float, float, float]:
    """
    Calcule la "perte solaire" (kWh) en HP, HC et total.
    Surproduction(t) = max(PV(t) - Conso(t), 0).
    """
    if df.empty:
        return (0.0, 0.0, 0.0)
    df_calc = df.copy()
    df_calc["lost_solar"] = df_calc["solar_production"] - df_calc["consumption_kwh"]
    df_calc.loc[df_calc["lost_solar"] < 0, "lost_solar"] = 0
    lost_hp = df_calc.loc[df_calc["is_hp"] == True, "lost_solar"].sum()
    lost_hc = df_calc.loc[df_calc["is_hp"] == False, "lost_solar"].sum()
    lost_total = df_calc["lost_solar"].sum()
    return lost_hp, lost_hc, lost_total


def compute_auto_consumption_ratio(df: pd.DataFrame) -> float:
    """
    Taux d'autoconsommation = 100 * ( production PV consommée / production PV totale ).
    production PV consommée = sum( min(conso, PV) ) sur tout l'intervalle.
    """
    if df.empty:
        return 0.0
    total_pv = df["solar_production"].sum()
    if total_pv <= 0:
        return 0.0
    # min(consommation, production) point par point
    used_pv = (pd.DataFrame({
        "used": df[["consumption_kwh", "solar_production"]].min(axis=1)
    }))["used"].sum()
    return used_pv / total_pv * 100


def compute_solar_coverage_ratio(df: pd.DataFrame) -> float:
    """
    Taux de couverture solaire = 100 * ( production PV consommée / consommation totale ).
    """
    if df.empty:
        return 0.0
    total_conso = df["consumption_kwh"].sum()
    if total_conso <= 0:
        return 0.0
    used_pv = (pd.DataFrame({
        "used": df[["consumption_kwh", "solar_production"]].min(axis=1)
    }))["used"].sum()
    return used_pv / total_conso * 100


# -------------- GÉNÉRATION DE CARDS --------------

def create_3column_card(
        title: str,
        hp_val: float,
        hc_val: float,
        total_val: float,
        suffix: str = "",
        help_text: str = ""
) -> dbc.Card:
    """
    Crée une carte (Card) avec 3 colonnes : HP | HC | Total.
    Ajoute un petit "?" pour afficher un tooltip si help_text est fourni.
    """
    # Génère un ID unique pour ne pas avoir de conflit
    tooltip_id = f"tooltip-{uuid.uuid4()}"

    card_header_children = [title]

    if help_text:
        # On ajoute un petit span "?" sur lequel on met le tooltip
        card_header_children.append(
            html.Span(
                " ?",
                id=tooltip_id,
                style={"cursor": "pointer", "color": "blue", "marginLeft": "5px"}
            )
        )

    card = dbc.Card([
        dbc.CardHeader(card_header_children),

        # Le tooltip (n'apparaît que si help_text est non vide)
        dbc.Tooltip(help_text, target=tooltip_id, placement="auto") if help_text else None,

        dbc.CardBody(
            dbc.Row([
                dbc.Col([
                    html.H6("HP", className="text-muted"),
                    html.H4(f"{hp_val:.2f}{suffix}", className="card-title")
                ], className="text-center"),

                dbc.Col([
                    html.H6("HC", className="text-muted"),
                    html.H4(f"{hc_val:.2f}{suffix}", className="card-title")
                ], className="text-center"),

                dbc.Col([
                    html.H6("Total", className="text-muted"),
                    html.H4(f"{total_val:.2f}{suffix}", className="card-title")
                ], className="text-center"),
            ], justify="center")
        )
    ], className="shadow-sm")

    return card


def create_1column_card(title: str, value: float, suffix: str = "", help_text: str = "") -> dbc.Card:
    """
    Carte avec un seul champ de valeur (ex: moyenne).
    Avec un paramètre help_text pour afficher un tooltip si besoin.
    """
    tooltip_id = f"tooltip-{uuid.uuid4()}"

    card_header_children = [title]
    if help_text:
        card_header_children.append(
            html.Span(
                " ?",
                id=tooltip_id,
                style={"cursor": "pointer", "color": "blue", "marginLeft": "5px"}
            )
        )

    card = dbc.Card([
        dbc.CardHeader(card_header_children),
        dbc.Tooltip(help_text, target=tooltip_id, placement="auto") if help_text else None,

        dbc.CardBody([
            html.H4(f"{value:.2f}{suffix}", className="card-title text-center")
        ])
    ], className="shadow-sm")

    return card


def create_2column_card(title: str, val_col1: str, val_col2: str, help_text: str = "") -> dbc.Card:
    """
    Carte avec 2 colonnes (par exemple pour afficher une valeur + la date/heure).
    On passe des strings déjà formatées (par ex. '12.34 kWh', '2024-01-06 13:00').
    Ajoute un petit "?" pour afficher un tooltip si help_text est fourni.
    """
    tooltip_id = f"tooltip-{uuid.uuid4()}"

    card_header_children = [title]
    if help_text:
        card_header_children.append(
            html.Span(
                " ?",
                id=tooltip_id,
                style={"cursor": "pointer", "color": "blue", "marginLeft": "5px"}
            )
        )

    card = dbc.Card([
        dbc.CardHeader(card_header_children),
        dbc.Tooltip(help_text, target=tooltip_id, placement="auto") if help_text else None,

        dbc.CardBody(
            dbc.Row([
                dbc.Col(html.H4(val_col1, className="card-title text-center")),
                dbc.Col(html.H4(val_col2, className="card-title text-center"))
            ], justify="center")
        )
    ], className="shadow-sm")

    return card


# -------------- LAYOUT --------------

app.layout = dbc.Container(
    [
        dbc.Row(dbc.Col(html.H1("Visualisation interactive", className="text-center my-4 text-primary"))),

        dbc.Row([
            dbc.Col([
                html.Div([
                    html.H5("Filtres", className="text-info"),
                    html.Label("Date de début:", className="fw-bold"),
                    dcc.DatePickerSingle(
                        id='start-date',
                        date=datetime.date(2024, 1, 1),
                        display_format="DD/MM/YYYY",
                        className="mb-3"
                    ),
                    html.Br(),
                    html.Label("Date de fin:", className="fw-bold"),
                    dcc.DatePickerSingle(
                        id='end-date',
                        date=datetime.date(2024, 1, 7),
                        display_format="DD/MM/YYYY",
                        className="mb-3"
                    ),
                    html.Br(),
                    html.Label("Regrouper par :", className="fw-bold"),
                    dcc.Dropdown(
                        id='aggregation-dropdown',
                        options=[
                            {"label": "Brut (30 min)", "value": "30min"},
                            {"label": "Heure", "value": "H"},
                            {"label": "Jour", "value": "D"},
                            {"label": "Semaine", "value": "W"},
                            {"label": "Mois", "value": "M"},
                        ],
                        value="30min",
                        clearable=False,
                        className="mb-3"
                    ),
                    html.Br(),
                    html.Label("Données météo à afficher :", className="fw-bold"),
                    dcc.Checklist(
                        id='weather-variables',
                        options=[{"label": label, "value": key} for key, label in METEO_VARIABLES.items()],
                        value=[],
                        className="mb-3"
                    )
                ], className="bg-light p-3 rounded shadow-sm")
            ], width=3),

            dbc.Col(dcc.Graph(id='consumption-graph', config={'scrollZoom': True}), width=9),
        ], className="my-3"),

        dbc.Row(dbc.Col(html.Div(id='output-metrics'), className="mt-4")),
        dbc.Row(id='extra-stats', className="mt-4")
    ],
    fluid=True
)


# -------------- CALLBACK --------------

@app.callback(
    [
        Output('consumption-graph', 'figure'),
        Output('output-metrics', 'children'),
        Output('extra-stats', 'children')
    ],
    [
        Input('start-date', 'date'),
        Input('end-date', 'date'),
        Input('aggregation-dropdown', 'value'),
        Input('weather-variables', 'value'),
        Input('consumption-graph', 'relayoutData')
    ]
)
def update_graph_and_metrics(start_dt, end_dt, aggregation, weather_vars, relayout_data):
    if not start_dt or not end_dt:
        return go.Figure(), "Veuillez sélectionner une période valide.", []

    session = get_session(get_engine())
    s_date = datetime.datetime.fromisoformat(start_dt)
    e_date = datetime.datetime.fromisoformat(end_dt)

    # 1) Données de consommation
    records = session.query(ConsumptionRecord).filter(
        ConsumptionRecord.start_time >= s_date,
        ConsumptionRecord.start_time <= e_date
    ).order_by(ConsumptionRecord.start_time).all()

    if not records:
        return go.Figure(), "Aucune donnée disponible pour cette période.", []

    df = pd.DataFrame({
        'start_time': [r.start_time for r in records],
        'consumption_kwh': [r.consumption_kwh for r in records]
    })
    df.set_index('start_time', inplace=True)

    # 2) Données météo
    weather_records = session.query(Weather).filter(
        Weather.time >= s_date,
        Weather.time <= e_date
    ).order_by(Weather.time).all()

    if weather_records:
        weather_df = pd.DataFrame([
            {
                "time": w.time,
                **{key: getattr(w, key, None) for key in METEO_VARIABLES.keys()}
            }
            for w in weather_records
        ])
        weather_df.set_index('time', inplace=True)
        df = df.join(weather_df, how='left')

    # 3) Production PV
    settings = get_or_create_settings(session)
    df["solar_production"] = compute_solar_production(df, settings)

    # 4) HP / HC
    df["hour"] = df.index.hour
    df["is_hp"] = df["hour"].apply(lambda x: True if 6 <= x < 22 else False)

    # 5) Regroupement
    if aggregation == "H":
        df = df.resample("H").mean()
    elif aggregation == "D":
        df = df.resample("D").mean()
    elif aggregation == "W":
        df = df.resample("W").mean()
    elif aggregation == "M":
        df = df.resample("M").mean()

    # 6) Zoom
    if relayout_data and "xaxis.range[0]" in relayout_data and "xaxis.range[1]" in relayout_data:
        zoom_start = pd.to_datetime(relayout_data["xaxis.range[0]"])
        zoom_end = pd.to_datetime(relayout_data["xaxis.range[1]"])
        df_zoom = df[(df.index >= zoom_start) & (df.index <= zoom_end)]
        if df_zoom.empty:
            df_zoom = df
    else:
        df_zoom = df

    # 7) TALO, PICS...
    talon_value = compute_talon_on_df(df_zoom)  # Hypothétique
    peak_consumption = df_zoom["consumption_kwh"].max()
    peak_consumption_time = (
        df_zoom["consumption_kwh"].idxmax() if not df_zoom.empty else None
    )
    peak_production = df_zoom["solar_production"].max()
    peak_production_time = (
        df_zoom["solar_production"].idxmax() if not df_zoom.empty else None
    )

    # 8) Conso / Coût (SANS PV)
    hp_consumption, hc_consumption, total_conso = compute_hp_hc_values(df_zoom, "consumption_kwh")
    cost_hp, cost_hc, cost_no_pv = compute_cost_hp_hc(df_zoom, settings)

    # 9) Conso / Coût (AVEC PV)
    hp_consumption_adj, hc_consumption_adj, total_conso_adj = (0, 0, 0)
    cost_hp_adj, cost_hc_adj, cost_with_pv = (0, 0, 0)
    if not df_zoom.empty:
        # net = max(conso - PV, 0)
        df_zoom_calc = df_zoom.copy()
        df_zoom_calc["net_consumption"] = df_zoom_calc["consumption_kwh"] - df_zoom_calc["solar_production"]
        df_zoom_calc.loc[df_zoom_calc["net_consumption"] < 0, "net_consumption"] = 0

        hp_consumption_adj, hc_consumption_adj, total_conso_adj = compute_hp_hc_values(df_zoom_calc, "net_consumption")
        cost_hp_adj, cost_hc_adj, cost_with_pv = compute_cost_with_pv_hp_hc(df_zoom, settings)

    # 10) Production solaire
    hp_production, hc_production, total_solar_production = compute_hp_hc_values(df_zoom, "solar_production")

    # 11) Pertes solaires (kWh)
    lost_hp_kwh, lost_hc_kwh, lost_total_kwh = compute_solar_loss_hp_hc(df_zoom)

    # 12) Autres stats : autoconsommation + couverture + moyenne conso
    avg_consumption = df_zoom["consumption_kwh"].mean() if not df_zoom.empty else 0.0
    auto_consumption_pct = compute_auto_consumption_ratio(df_zoom)  # en %
    coverage_pct = compute_solar_coverage_ratio(df_zoom)            # en %

    # ---- GRAPH ----
    fig = go.Figure()
    # Courbe conso
    fig.add_trace(go.Scatter(
        x=df.index,
        y=df["consumption_kwh"],
        mode='lines+markers',
        name='Consommation (kWh)',
        marker=dict(size=3)
    ))
    # Météo
    for var in weather_vars:
        if var in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index,
                y=df[var],
                mode='lines',
                name=METEO_VARIABLES[var],
                yaxis="y2"
            ))
    # Production PV
    fig.add_trace(go.Scatter(
        x=df.index,
        y=df["solar_production"],
        mode="lines",
        name="Production PV (kWh)",
        line=dict(dash="dot")
    ))
    # Talon (ligne horizontale)
    fig.add_hline(
        y=talon_value,
        line_dash="dash",
        line_color="orange",
        annotation_text=f"Talon : {talon_value:.2f} kWh",
        annotation_position="bottom right"
    )
    # Pic conso
    if pd.notna(peak_consumption) and peak_consumption_time is not None:
        fig.add_trace(go.Scatter(
            x=[peak_consumption_time],
            y=[peak_consumption],
            mode="markers",
            marker=dict(size=10, color="red", symbol="triangle-up"),
            name="Pic Conso"
        ))
    # Pic PV
    if pd.notna(peak_production) and peak_production_time is not None:
        fig.add_trace(go.Scatter(
            x=[peak_production_time],
            y=[peak_production],
            mode="markers",
            marker=dict(size=10, color="green", symbol="triangle-up"),
            name="Pic PV"
        ))
    fig.update_layout(
        title="Consommation électrique et météo (Zoomable)",
        xaxis_title="Date et Heure",
        yaxis_title="Consommation / Production (kWh)",
        yaxis2=dict(
            title="Météo",
            overlaying="y",
            side="right",
            showgrid=False
        ),
        hovermode="x unified",
        uirevision="consumption-graph"
    )

    # ---- CARTES ----

    # 1) Prix (sans PV)
    card_price_no_pv = create_3column_card(
        title="Prix (sans PV)",
        hp_val=cost_hp,
        hc_val=cost_hc,
        total_val=cost_no_pv,
        suffix=" €",
        help_text=(
            "Coût estimé de la consommation électrique sans tenir compte de la production solaire. "
            "Le coût est calculé séparément pour les heures pleines (HP) et les heures creuses (HC), "
            "puis totalisé."
        )
    )

    # 2) Prix (avec PV)
    card_price_with_pv = create_3column_card(
        title="Prix (avec PV)",
        hp_val=cost_hp_adj,
        hc_val=cost_hc_adj,
        total_val=cost_with_pv,
        suffix=" €",
        help_text=(
            "Coût total de la consommation après déduction de la production solaire. "
            "Chaque point est calculé comme : max(consommation - production, 0). "
            "Les surplus de production sont perdus et non déduits."
        )
    )

    # 3) Conso (sans PV)
    card_conso_no_pv = create_3column_card(
        title="Conso (sans PV)",
        hp_val=hp_consumption,
        hc_val=hc_consumption,
        total_val=total_conso,
        suffix=" kWh",
        help_text=(
            "Consommation totale en kilowattheures (kWh), répartie entre heures pleines (HP) "
            "et heures creuses (HC). Ne prend pas en compte la production solaire."
        )
    )

    # 4) Conso (avec PV)
    card_conso_with_pv = create_3column_card(
        title="Conso (avec PV)",
        hp_val=hp_consumption_adj,
        hc_val=hc_consumption_adj,
        total_val=total_conso_adj,
        suffix=" kWh",
        help_text=(
            "Consommation nette après prise en compte de la production solaire. "
            "Chaque point est calculé comme : max(consommation - production, 0). "
            "Les surplus de production ne sont pas déduits."
        )
    )

    # 5) Production solaire
    card_pv = create_3column_card(
        title="Production solaire",
        hp_val=hp_production,
        hc_val=hc_production,
        total_val=total_solar_production,
        suffix=" kWh",
        help_text=(
            "Production totale d'énergie solaire en kilowattheures (kWh), répartie entre heures pleines (HP) "
            "et heures creuses (HC). Cette valeur correspond à la production brute générée par les panneaux solaires."
        )
    )

    # 6) Pertes solaires (kWh)
    card_lost_solar_kwh = create_3column_card(
        title="Pertes solaires (kWh)",
        hp_val=lost_hp_kwh,
        hc_val=lost_hc_kwh,
        total_val=lost_total_kwh,
        suffix=" kWh",
        help_text=(
            "Quantité d'énergie solaire perdue en raison de la surproduction par rapport à la consommation. "
            "Calculée comme : max(production - consommation, 0)."
        )
    )

    # 7) Moyenne de consommation (simple, 1 colonne)
    card_avg_conso = create_1column_card(
        title="Moyenne de conso",
        value=avg_consumption,
        suffix=" kWh",
        help_text="Consommation moyenne (kWh) sur la période analysée, calculée en prenant la moyenne des valeurs mesurées."
    )

    # 8) Pic de consommation (2 colonnes : la valeur et la date/heure)
    val_consumption_str = f"{peak_consumption:.2f} kWh" if pd.notna(peak_consumption) else "N/A"
    time_consumption_str = str(peak_consumption_time) if peak_consumption_time else "N/A"
    card_peak_conso = create_2column_card(
        title="Pic de consommation",
        val_col1=val_consumption_str,
        val_col2=time_consumption_str,
        help_text=(
            "Valeur maximale de la consommation électrique (kWh) atteinte pendant la période analysée, "
            "accompagnée de la date et de l'heure à laquelle ce pic s'est produit."
        )
    )

    # 9) Pic de production (2 colonnes : la valeur et la date/heure)
    val_production_str = f"{peak_production:.2f} kWh" if pd.notna(peak_production) else "N/A"
    time_production_str = str(peak_production_time) if peak_production_time else "N/A"
    card_peak_production = create_2column_card(
        title="Pic de production",
        val_col1=val_production_str,
        val_col2=time_production_str,
        help_text=(
            "Valeur maximale de la production solaire (kWh) atteinte pendant la période analysée, "
            "accompagnée de la date et de l'heure à laquelle ce pic s'est produit."
        )
    )

    # 10) Taux d'autoconsommation (1 colonne)
    card_auto_consumption = create_1column_card(
        title="Taux d'autoconsommation",
        value=auto_consumption_pct,
        suffix=" %",
        help_text=(
            "Pourcentage de l'énergie solaire produite qui est directement consommée (non injectée/perdue). "
            "Calcul : 100 * (min(consommation, production) / production totale)."
        )
    )

    # 11) Taux de couverture solaire (1 colonne)
    card_coverage = create_1column_card(
        title="Taux de couverture solaire",
        value=coverage_pct,
        suffix=" %",
        help_text=(
            "Pourcentage de la consommation totale qui est couverte par la production solaire. "
            "Calcul : 100 * (min(consommation, production) / consommation totale)."
        )
    )
    # Organisation en lignes
    # Ici, on fait 3 ou 4 cartes par ligne, à vous d'agencer.
    row1 = dbc.Row([
        dbc.Col(card_price_no_pv, width=4),
        dbc.Col(card_price_with_pv, width=4),
        dbc.Col(card_avg_conso, width=4),
    ], className="gy-3")

    row2 = dbc.Row([
        dbc.Col(card_conso_no_pv, width=4),
        dbc.Col(card_conso_with_pv, width=4),
        dbc.Col(card_pv, width=4),
    ], className="gy-3")

    row3 = dbc.Row([
        dbc.Col(card_lost_solar_kwh, width=4),
        dbc.Col(card_peak_conso, width=4),
        dbc.Col(card_peak_production, width=4),
    ], className="gy-3")

    row4 = dbc.Row([
        dbc.Col(card_auto_consumption, width=6),
        dbc.Col(card_coverage, width=6),
    ], className="gy-3")

    metrics_div = " "  # ou un petit texte "Statistiques"
    extra_stats_div = [row1, row2, row3, row4]

    return fig, metrics_div, extra_stats_div


if __name__ == "__main__":
    app.run_server(debug=True, port=8050)
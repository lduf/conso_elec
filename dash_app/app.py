import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objs as go
import pandas as pd
import datetime
import dash_bootstrap_components as dbc

from db.database import get_engine, get_session, ConsumptionRecord, Weather, get_or_create_settings
from analytics.metrics import compute_talon_on_df

# Charger Dash avec le thème Bootstrap
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.FLATLY])
app.title = "Visualisation interactive - Dash"

# Liste des variables météorologiques disponibles
METEO_VARIABLES = {
    "temperature_2m": "Température (°C)",
    "precipitation": "Précipitations (mm)",
    "cloud_cover": "Couverture nuageuse (%)",
    "shortwave_radiation": "Rayonnement solaire (W/m²)",
    "direct_radiation": "Rayonnement direct (W/m²)",
    "wind_speed_10m": "Vitesse du vent (m/s)"
}


def compute_solar_production(df: pd.DataFrame, settings) -> pd.Series:
    """
    Calcule la production photovoltaïque en kWh, en se basant sur la colonne `shortwave_radiation`.
    """
    if "shortwave_radiation" not in df.columns:
        return pd.Series(0, index=df.index)

    area = settings.solar_area  # Surface en m²
    efficiency = settings.solar_efficiency / 100  # Efficacité en fraction
    loss = settings.solar_loss / 100  # Pertes en fraction

    # Production photovoltaïque en kWh
    solar_production = (df["shortwave_radiation"] * area * efficiency * (1 - loss)) / 1000
    return solar_production


def compute_adjusted_cost(consumption: pd.Series, solar_production: pd.Series, hp_cost: float, hc_cost: float) -> float:
    """
    Calcule le coût ajusté après prise en compte de la production solaire.
    (Hypothèse simplifiée : tout est facturé au tarif HP.)
    """
    net_consumption = consumption - solar_production
    net_consumption[net_consumption < 0] = 0  # Surproduction perdue
    return (net_consumption * hp_cost).sum()


# Layout principal
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
                        value=[],  # Par défaut, aucune variable météo n'est affichée
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
        Input('consumption-graph', 'relayoutData')  # On récupère le relayoutData pour détecter le zoom
    ],
    # pas besoin de State ici, on peut tout mettre en Input
)
def update_graph_and_metrics(start_dt, end_dt, aggregation, weather_vars, relayout_data):
    if not start_dt or not end_dt:
        return go.Figure(), "Veuillez sélectionner une période valide.", []

    session = get_session(get_engine())
    s_date = datetime.datetime.fromisoformat(start_dt)
    e_date = datetime.datetime.fromisoformat(end_dt)

    # 1) Récupération des données de consommation
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

    # 2) Récupération des données météo
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

    # 3) Ajout de la production PV
    settings = get_or_create_settings(session)
    df["solar_production"] = compute_solar_production(df, settings)

    # 4) HP / HC (exemple : 6h -> 22h = HP, le reste HC)
    df["hour"] = df.index.hour
    df["is_hp"] = df["hour"].apply(lambda x: True if 6 <= x < 22 else False)

    # 5) Regroupement temporel
    if aggregation == "H":
        df = df.resample("H").mean()
    elif aggregation == "D":
        df = df.resample("D").mean()
    elif aggregation == "W":
        df = df.resample("W").mean()
    elif aggregation == "M":
        df = df.resample("M").mean()
    # "30min" => on ne touche pas (données brutes)

    # -- GESTION DU ZOOM : on filtre df en fonction du range visible --
    #   relayoutData contient, entre autres, "xaxis.range[0]" et "xaxis.range[1]" si l’utilisateur fait un zoom
    if relayout_data and "xaxis.range[0]" in relayout_data and "xaxis.range[1]" in relayout_data:
        zoom_start = pd.to_datetime(relayout_data["xaxis.range[0]"])
        zoom_end = pd.to_datetime(relayout_data["xaxis.range[1]"])
        # On ne garde que la portion zoomée
        df_zoom = df[(df.index >= zoom_start) & (df.index <= zoom_end)]
        # Si le zoom est totalement en dehors des données, df_zoom risque d’être vide
        if df_zoom.empty:
            df_zoom = df
    else:
        # Pas de zoom => on prend la totalité du DF
        df_zoom = df

    # 6) Calcul du talon, pic de conso et pic de production SUR LA ZONE ZOOMÉE
    #    (pour refléter la portion visible)
    talon_value = compute_talon_on_df(df_zoom)  # hypothétique
    peak_consumption = df_zoom["consumption_kwh"].max()
    # idxmax() donne l'index où se trouve le pic
    peak_consumption_time = df_zoom["consumption_kwh"].idxmax()

    peak_production = df_zoom["solar_production"].max()
    peak_production_time = df_zoom["solar_production"].idxmax()

    # 7) Calcul des consommations HP / HC, coûts, etc. SUR LA ZONE ZOOMÉE
    hp_consumption = df_zoom[df_zoom["is_hp"] == True]["consumption_kwh"].sum() if "is_hp" in df_zoom.columns else 0
    hc_consumption = df_zoom[df_zoom["is_hp"] == False]["consumption_kwh"].sum() if "is_hp" in df_zoom.columns else 0

    cost_hp = hp_consumption * settings.hp_cost
    cost_hc = hc_consumption * settings.hc_cost
    cost_no_pv = cost_hp + cost_hc

    avg_consumption = df_zoom["consumption_kwh"].mean() if not df_zoom.empty else 0

    # Coût ajusté (avec PV)
    total_cost_adjusted = compute_adjusted_cost(
        df_zoom["consumption_kwh"], df_zoom["solar_production"],
        settings.hp_cost, settings.hc_cost
    )

    # HP/HC avec PV
    net_consumption = df_zoom["consumption_kwh"] - df_zoom["solar_production"]
    net_consumption[net_consumption < 0] = 0
    hp_consumption_adj = net_consumption[df_zoom["is_hp"] == True].sum() if "is_hp" in df_zoom.columns else 0
    hc_consumption_adj = net_consumption[df_zoom["is_hp"] == False].sum() if "is_hp" in df_zoom.columns else 0
    cost_hp_adj = hp_consumption_adj * settings.hp_cost
    cost_hc_adj = hc_consumption_adj * settings.hc_cost

    # 8) Construction du graphique
    fig = go.Figure()

    # Trace de consommation
    fig.add_trace(go.Scatter(
        x=df.index,  # on met tout le df en x pour le rendu global
        y=df['consumption_kwh'],
        mode='lines+markers',
        name='Consommation (kWh)',
        marker=dict(size=3)
    ))

    # Traces météo (axe de droite)
    for var in weather_vars:
        if var in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index,
                y=df[var],
                mode='lines',
                name=METEO_VARIABLES[var],
                yaxis="y2"
            ))

    # Production PV (même axe que la conso)
    fig.add_trace(go.Scatter(
        x=df.index,
        y=df["solar_production"],
        mode="lines",
        name="Production PV (kWh)",
        line=dict(dash="dot")
    ))

    # ---- Talon (ligne horizontale) ----
    fig.add_hline(
        y=talon_value,
        line_dash="dash",
        line_color="orange",
        annotation_text=f"Talon : {talon_value:.2f} kWh",
        annotation_position="bottom right"
    )

    # ---- Pic de consommation (point rouge) ----
    if pd.notna(peak_consumption) and peak_consumption_time is not None:
        fig.add_trace(
            go.Scatter(
                x=[peak_consumption_time],
                y=[peak_consumption],
                mode="markers",
                marker=dict(size=10, color="red", symbol="triangle-up"),
                name="Pic Conso"
            )
        )

    # ---- Pic de production PV (point vert) ----
    if pd.notna(peak_production) and peak_production_time is not None:
        fig.add_trace(
            go.Scatter(
                x=[peak_production_time],
                y=[peak_production],
                mode="markers",
                marker=dict(size=10, color="green", symbol="triangle-up"),
                name="Pic PV"
            )
        )

    # Mise en forme
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
        # Clé uirevision pour conserver l'affichage (mais on recalcule quand même la zone zoomée)
        uirevision="consumption-graph"
    )

    # 9) Création des cartes de métriques
    total_solar_production = df_zoom["solar_production"].sum()

    # Premier bloc de cartes
    cards_main = dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader("Production PV totale"),
            dbc.CardBody(html.H4(f"{total_solar_production:.2f} kWh", className="card-title"))
        ], className="shadow-sm"), width=3),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Coût ajusté (avec PV)"),
            dbc.CardBody(html.H4(f"{total_cost_adjusted:.2f} €", className="card-title"))
        ], className="shadow-sm"), width=3),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Consommation totale"),
            dbc.CardBody(html.H4(f"{df_zoom['consumption_kwh'].sum():.2f} kWh", className="card-title"))
        ], className="shadow-sm"), width=3),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Coût estimé (sans PV)"),
            dbc.CardBody(html.H4(f"{cost_no_pv:.2f} €", className="card-title"))
        ], className="shadow-sm"), width=3)
    ], className="gy-3")

    # Second bloc (stats détaillées)
    cards_extra = [
        dbc.Col(dbc.Card([
            dbc.CardHeader("Talon"),
            dbc.CardBody(html.H4(f"{talon_value:.2f} kWh", className="card-title"))
        ], className="shadow-sm"), width=2),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Pic Conso"),
            dbc.CardBody(html.H4(f"{peak_consumption:.2f} kWh", className="card-title"))
        ], className="shadow-sm"), width=2),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Pic PV"),
            dbc.CardBody(html.H4(f"{peak_production:.2f} kWh", className="card-title"))
        ], className="shadow-sm"), width=2),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Conso moyenne"),
            dbc.CardBody(html.H4(f"{avg_consumption:.2f} kWh", className="card-title"))
        ], className="shadow-sm"), width=2),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Conso HP"),
            dbc.CardBody(html.H4(f"{hp_consumption:.2f} kWh", className="card-title"))
        ], className="shadow-sm"), width=2),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Conso HC"),
            dbc.CardBody(html.H4(f"{hc_consumption:.2f} kWh", className="card-title"))
        ], className="shadow-sm"), width=2),
    ]

    cards_extra2 = [
        dbc.Col(dbc.Card([
            dbc.CardHeader("Conso HP (avec PV)"),
            dbc.CardBody(html.H4(f"{hp_consumption_adj:.2f} kWh", className="card-title"))
        ], className="shadow-sm"), width=3),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Conso HC (avec PV)"),
            dbc.CardBody(html.H4(f"{hc_consumption_adj:.2f} kWh", className="card-title"))
        ], className="shadow-sm"), width=3),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Coût HP (avec PV)"),
            dbc.CardBody(html.H4(f"{cost_hp_adj:.2f} €", className="card-title"))
        ], className="shadow-sm"), width=3),

        dbc.Col(dbc.Card([
            dbc.CardHeader("Coût HC (avec PV)"),
            dbc.CardBody(html.H4(f"{cost_hc_adj:.2f} €", className="card-title"))
        ], className="card-title shadow-sm"), width=3),
    ]

    metrics_div = html.Div([cards_main])
    extra_stats_div = [
        dbc.Row(cards_extra, className="gy-3"),
        dbc.Row(cards_extra2, className="gy-3")
    ]

    return fig, metrics_div, extra_stats_div


if __name__ == "__main__":
    app.run_server(debug=True, port=8050)
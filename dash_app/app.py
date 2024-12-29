# dash_app/app.py

import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objs as go
import pandas as pd
import datetime
import dash_bootstrap_components as dbc

from db.database import get_engine, get_session, ConsumptionRecord, get_or_create_settings
from analytics.metrics import compute_all_metrics, compute_talon_on_df

# Charger Dash avec le thème Bootstrap
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.FLATLY])
app.title = "Visualisation interactive - Dash"

# App layout
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
                        className="mb-3"
                    ),
                    html.Br(),
                    html.Label("Date de fin:", className="fw-bold"),
                    dcc.DatePickerSingle(
                        id='end-date',
                        date=datetime.date(2024, 1, 7),
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
                        className="mb-3"
                    )
                ], className="bg-light p-3 rounded")
            ], width=3),

            dbc.Col(dcc.Graph(id='consumption-graph', config={'scrollZoom': True}), width=9),
        ], className="my-3"),

        dbc.Row(dbc.Col(html.Div(id='output-metrics'), className="mt-4"))
    ],
    fluid=True
)


@app.callback(
    [Output('consumption-graph', 'figure'),
     Output('output-metrics', 'children')],
    [Input('start-date', 'date'),
     Input('end-date', 'date'),
     Input('aggregation-dropdown', 'value'),
     Input('consumption-graph', 'relayoutData')],
    [State('consumption-graph', 'figure')]
)
def update_graph_and_metrics(start_dt, end_dt, aggregation, relayout_data, current_figure):
    """
    Charge les données, regroupe les consommations et met à jour le graphique
    et les métriques, en fonction de la période et des interactions (zoom, regroupement).
    """
    if not start_dt or not end_dt:
        return go.Figure(), "Veuillez sélectionner une période valide."

    session = get_session(get_engine())
    s_date = datetime.datetime.fromisoformat(start_dt)
    e_date = datetime.datetime.fromisoformat(end_dt)

    # Récupération des données dans la période
    records = session.query(ConsumptionRecord).filter(
        ConsumptionRecord.start_time >= s_date,
        ConsumptionRecord.start_time <= e_date
    ).order_by(ConsumptionRecord.start_time).all()

    if not records:
        return go.Figure(), "Aucune donnée disponible pour cette période."

    df = pd.DataFrame({
        'start_time': [r.start_time for r in records],
        'consumption_kwh': [r.consumption_kwh for r in records]
    })
    df.set_index('start_time', inplace=True)

    # Gestion du zoom (relayoutData)
    if relayout_data and 'xaxis.range[0]' in relayout_data and 'xaxis.range[1]' in relayout_data:
        zoom_start = pd.to_datetime(relayout_data['xaxis.range[0]'])
        zoom_end = pd.to_datetime(relayout_data['xaxis.range[1]'])
        df = df.loc[zoom_start:zoom_end]

    # Regroupement des données
    if aggregation == "H":
        df = df.resample("H").sum()
    elif aggregation == "D":
        df = df.resample("D").sum()
    elif aggregation == "W":
        df = df.resample("W").sum()
    elif aggregation == "M":
        df = df.resample("M").sum()

    # Calculs principaux
    settings = get_or_create_settings(session)
    results = compute_all_metrics(
        df,
        settings.hp_cost,
        settings.hc_cost,
        settings.hp_start,
        settings.hp_end
    )
    talon_val = compute_talon_on_df(df)
    max_val = df['consumption_kwh'].max() if "consumption_kwh" in df else 0
    max_index = df['consumption_kwh'].idxmax() if max_val > 0 else None

    # Création du graphique
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index,
        y=df['consumption_kwh'],
        mode='lines+markers',
        name='Consommation'
    ))

    # Ajout du talon
    fig.add_hline(
        y=talon_val,
        line_dash="dash",
        annotation_text=f"Talon = {talon_val:.2f} kW",
        annotation_position="bottom right",
        line_color="red"
    )

    # Ajout du maximum
    if max_index is not None:
        fig.add_trace(go.Scatter(
            x=[max_index],
            y=[max_val],
            mode='markers+text',
            text=[f"Max: {max_val:.2f}"],
            textposition="top center",
            marker=dict(color="orange", size=12),
            name='Max'
        ))

    fig.update_layout(
        title="Consommation électrique (Zoomable)",
        xaxis_title="Date et Heure",
        yaxis_title="Consommation (kWh)",
        hovermode="x unified"
    )

    # Création des métriques
    metrics_div = dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader("Talon"),
            dbc.CardBody(html.H4(f"{results['talon']:.2f} kW", className="card-title"))
        ]), width=3),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Consommation totale"),
            dbc.CardBody(html.H4(f"{results['total_conso']:.2f} kWh", className="card-title"))
        ]), width=3),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Coût estimé"),
            dbc.CardBody(html.H4(f"{results['cost']:.2f} €", className="card-title"))
        ]), width=3),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Consommation moyenne"),
            dbc.CardBody(html.H4(f"{df['consumption_kwh'].mean():.2f} kWh", className="card-title"))
        ]), width=3),
        dbc.Col(dbc.Card([
            dbc.CardHeader("Écart-type"),
            dbc.CardBody(html.H4(f"{df['consumption_kwh'].std():.2f} kWh", className="card-title"))
        ]), width=3)
    ], className="mt-4")

    return fig, metrics_div


if __name__ == "__main__":
    app.run_server(debug=True, port=8050)
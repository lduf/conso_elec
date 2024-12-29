# analytics/visualizations.py

import plotly.graph_objs as go
from sqlalchemy.orm import Session
from db.database import ConsumptionRecord
from analytics.calculations import calculate_base_load

def plot_consumption_over_time_plotly(session: Session):
    """
    Trace un graphique Plotly de la consommation
    en fonction du temps (start_time).
    """
    records = session.query(ConsumptionRecord).order_by(ConsumptionRecord.start_time).all()
    if not records:
        return None

    x = [r.start_time for r in records]
    y = [r.consumption_kwh for r in records]

    # Calcul du talon, par exemple
    base_load = calculate_base_load(session)

    # Création d'une figure Plotly
    fig = go.Figure()

    # Courbe de consommation
    fig.add_trace(go.Scatter(
        x=x,
        y=y,
        mode='lines+markers',
        name='Consommation'
    ))

    # Ligne horizontale pour le talon
    fig.add_hline(
        y=base_load,
        line_dash="dash",
        annotation_text=f"Talon = {base_load:.2f} kWh",
        annotation_position="top left",
        line_color="red"
    )

    # Mettre en évidence le point max
    max_val = max(y)
    max_index = y.index(max_val)
    max_time = x[max_index]
    fig.add_trace(go.Scatter(
        x=[max_time],
        y=[max_val],
        mode='markers+text',
        text=[f"Max: {max_val:.2f} kWh"],
        textposition="top center",
        marker=dict(color="orange", size=10),
        name='Max'
    ))

    fig.update_layout(
        title="Courbe de consommation électrique",
        xaxis_title="Date et Heure (début)",
        yaxis_title="Consommation (kWh)",
        hovermode="x unified"
    )
    return fig
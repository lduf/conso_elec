# analytics/metrics.py

def compute_cost_hp_hc(df, hp_cost, hc_cost, hp_start, hp_end):
    """
    Calcule le coût total selon que chaque enregistrement tombe en HP ou HC.
    df doit avoir un index 'start_time' (datetime) et une col 'consumption_kwh'.
    """
    total_cost = 0.0
    if df.empty:
        return total_cost

    for ts, row in df.iterrows():
        time_of_day = ts.time()
        if hp_start < hp_end:
            in_hp = (time_of_day >= hp_start) and (time_of_day < hp_end)
        else:
            in_hp = (time_of_day >= hp_start) or (time_of_day < hp_end)

        cost = row['consumption_kwh'] * (hp_cost if in_hp else hc_cost)
        total_cost += cost

    return total_cost


def compute_talon_on_df(df):
    """
    Exemple de calcul de talon : on prend le 5ᵉ percentile de la série
    consumption_kwh comme 'talon'.
    """
    if df.empty:
        return 0.0
    sorted_values = df['consumption_kwh'].sort_values()
    index_5pct = int(len(sorted_values) * 0.05)
    talon_val = sorted_values.iloc[index_5pct]
    return talon_val


def compute_all_metrics(df, hp_cost, hc_cost, hp_start, hp_end):
    """
    Calcule toutes les métriques nécessaires : talon, conso totale, coût ...
    """
    if df.empty:
        return {
            "talon": 0.0,
            "total_conso": 0.0,
            "cost": 0.0
        }
    talon_val = compute_talon_on_df(df)
    total_conso_val = df['consumption_kwh'].sum()
    total_cost_val = compute_cost_hp_hc(df, hp_cost, hc_cost, hp_start, hp_end)

    return {
        "talon": talon_val,
        "total_conso": total_conso_val,
        "cost": total_cost_val
    }
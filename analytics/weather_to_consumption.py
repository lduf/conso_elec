from db.database import ConsumptionRecord, Weather
from extraction.weather import fetch_weather_data, resample_weather_data, save_weather_data_to_db

def get_consumption_days(session):
    """
    Récupère les jours pour lesquels il existe des enregistrements de consommation.
    """
    consumption_days = session.query(ConsumptionRecord.start_time).distinct().all()
    return {record.start_time.date() for record in consumption_days}

def get_weather_date(session):
    """
    Récupère les dates pour lesquelles il existe des données météo.
    """
    weather_dates = session.query(Weather.time).distinct().all()
    return {record.time.date() for record in weather_dates}

def weather_data_to_collect():
    """
    Récupère les données qu'il faut récupérer en fonction des colonnes de la table Weather.
    """
    col_to_remove = ["id", "time"]
    weather_columns = Weather.__table__.columns.keys()
    for col in col_to_remove:
        weather_columns.remove(col)
    return weather_columns

def integrate_weather_with_consumption(session, latitude, longitude):
    """
    Associe la météo aux jours de consommation.
    """
    days = get_consumption_days(session)
    weather_days = get_weather_date(session)
    days = days - weather_days
    for day in days:
        weather_data = fetch_weather_data(latitude=latitude, longitude=longitude, start_date=day, end_date=day, variables=weather_data_to_collect())
        weather_resampled = resample_weather_data(weather_data)
        save_weather_data_to_db(session, weather_resampled)
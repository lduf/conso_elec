import pandas as pd
from datetime import datetime, date, timedelta
from typing import List
import logging
import requests_cache
from retry_requests import retry
import openmeteo_requests

# Configuration de cache et retry pour l'API Open-Meteo
cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

logging.basicConfig(level=logging.INFO)

def fetch_weather_data(
        latitude: float,
        longitude: float,
        start_date: date,
        end_date: date,
        variables: List[str]
) -> pd.DataFrame:
    """
    Récupère les données météo pour une plage de dates via l'API Open-Meteo.

    Args:
        latitude (float): Latitude de la localisation.
        longitude (float): Longitude de la localisation.
        start_date (date): Date de début.
        end_date (date): Date de fin.
        variables (List[str]): Liste des variables météo à récupérer.

    Returns:
        pd.DataFrame: Données météo sous forme de DataFrame.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": variables,
        "timezone": "Europe/Berlin",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat()
    }

    try:
        responses = openmeteo.weather_api(url, params=params)
        response = responses[0]  # On traite uniquement une localisation ici
    except Exception as e:
        logging.error(f"Erreur lors de l'appel à l'API Open-Meteo : {e}")
        return pd.DataFrame()

    # Extraction des données horaires
    hourly = response.Hourly()
    hourly_data = {
        "time": pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left"
        )
    }

    # Ajouter chaque variable récupérée à hourly_data
    for idx, variable in enumerate(variables):
        hourly_data[variable] = hourly.Variables(idx).ValuesAsNumpy()

    return pd.DataFrame(hourly_data)

def resample_weather_data(weather_df: pd.DataFrame) -> pd.DataFrame:
    """
    Rééchantillonne les données météo à des intervalles de 30 minutes.

    Args:
        weather_df (pd.DataFrame): DataFrame des données météo horaires.

    Returns:
        pd.DataFrame: DataFrame rééchantillonnée à 30 minutes.
    """
    if "time" not in weather_df.columns:
        raise ValueError("La colonne 'time' est requise dans le DataFrame.")

    weather_df.set_index("time", inplace=True)
    resampled_df = weather_df.resample("30min").interpolate("linear").reset_index()
    return resampled_df

def save_weather_data_to_db(session, weather_df: pd.DataFrame) -> None:
    """
    Sauvegarde les données météo interpolées dans la base de données.

    Args:
        session: Session SQLAlchemy active.
        weather_df (pd.DataFrame): DataFrame des données météo à sauvegarder.

    Returns:
        None
    """
    from db.database import Weather

    # Remplacer NaN ou NaT par None dans tout le DataFrame
    weather_df = weather_df.where(pd.notnull(weather_df), None)

    # Convertir le DataFrame en dictionnaire
    records = weather_df.to_dict(orient="records")

    # Préparer les objets Weather pour insertion
    weather_objects = [
        {
            "time": record["time"],
            "temperature_2m": record.get("temperature_2m"),
            "precipitation": record.get("precipitation"),
            "cloud_cover": record.get("cloud_cover"),
            "shortwave_radiation": record.get("shortwave_radiation"),
            "direct_radiation": record.get("direct_radiation"),
            "wind_speed_10m": record.get("wind_speed_10m"),
            "direct_normal_irradiance": record.get("direct_normal_irradiance"),
            "diffuse_radiation": record.get("diffuse_radiation")
        }
        for record in records
    ]

    # Utiliser une exécution SQL massive pour insérer les données
    session.execute(
        Weather.__table__.insert(),  # Insère directement dans la table Weather
        weather_objects
    )
    session.commit()
    logging.info(f"{len(weather_objects)} enregistrements météo sauvegardés avec succès.")

if __name__ == "__main__":

    pd.set_option('display.max_columns', None)  # Afficher toutes les colonnes
    pd.set_option('display.max_rows', None)     # Afficher toutes les lignes
    pd.set_option('display.width', 1000)       # Ajuster la largeur pour éviter les coupures

    # Paramètres de l'appel
    latitude = 48.68
    longitude = 3.2199998
    start_date = date(2024, 11, 27)
    end_date = date(2024, 11, 27)
    variables = [
        "temperature_2m", "precipitation",
        "precipitation", "cloud_cover", "shortwave_radiation", "direct_radiation", "wind_speed_10m", "direct_normal_irradiance", "diffuse_radiation",
    ]

    # Récupération des données météo
    weather_df = fetch_weather_data(latitude, longitude, start_date, end_date, variables)
    if weather_df.empty:
        logging.error("Aucune donnée météo récupérée.")
    else:
        logging.info(f"Données météo récupérées :\n{weather_df.head()}")


        # Rééchantillonnage à 30 minutes
        resampled_weather_df = resample_weather_data(weather_df)
        logging.info(f"Données rééchantillonnées :\n{resampled_weather_df.head()}")

        # Exemple d'écriture en base (à faire si nécessaire)
        # from db.database import get_session
        # session = get_session()
        # save_weather_data_to_db(session, resampled_weather_df)
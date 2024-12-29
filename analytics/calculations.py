# analytics/calculations.py

from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.database import ConsumptionRecord

def import_data_to_db(df, session: Session):
    """
    Importer les données d'un DataFrame dans la base de données,
    en prenant 'Début', 'Fin' et 'Valeur (en kW)' comme colonnes Excel.
    """
    records = []
    for _, row in df.iterrows():
        # Récupérer les valeurs dans le DataFrame
        start_str = row['Début']
        end_str = row['Fin']
        consumption_str = str(row['Valeur (en kW)']).replace(',', '.')

        # Convertir en float la consommation
        consumption = float(consumption_str)

        # Parser les dates/heure ; votre Excel semble au format "dd/mm/YYYY HH:MM:SS"
        start_time = datetime.strptime(start_str, "%d/%m/%Y %H:%M:%S")
        end_time = datetime.strptime(end_str, "%d/%m/%Y %H:%M:%S")

        # Créer l'objet pour SQLAlchemy
        record = ConsumptionRecord(
            start_time=start_time,
            end_time=end_time,
            consumption_kwh=consumption
        )
        records.append(record)

    # Insérer en base
    session.bulk_save_objects(records)
    session.commit()

def import_data_with_duplicates_management(df, session: Session):
    """
    Importer les données d'un DataFrame dans la base de données
    tout en gérant les doublons :
    - si un enregistrement (start_time, end_time) existe déjà
      et que la valeur est identique, on ignore.
    - si un enregistrement (start_time, end_time) existe déjà
      mais la valeur diffère, on soulève une exception (ou on
      renvoie un signal) pour permettre une décision à l'utilisateur.
    """
    conflicts = []

    for _, row in df.iterrows():
        start_str = row['Début']
        end_str = row['Fin']
        consumption_str = str(row['Valeur (en kW)']).replace(',', '.')
        consumption = float(consumption_str)

        start_time = datetime.strptime(start_str, "%d/%m/%Y %H:%M:%S")
        end_time = datetime.strptime(end_str, "%d/%m/%Y %H:%M:%S")

        existing_record = session.query(ConsumptionRecord).filter(
            ConsumptionRecord.start_time == start_time,
            ConsumptionRecord.end_time == end_time
        ).one_or_none()

        if existing_record:
            # Doublon potentiel
            if abs(existing_record.consumption_kwh - consumption) < 1e-6:
                # Les valeurs sont identiques, on ne fait rien
                continue
            else:
                # Conflit : même intervalle de temps, mais consommation différente
                conflicts.append({
                    'start_time': start_time,
                    'end_time': end_time,
                    'existing_value': existing_record.consumption_kwh,
                    'new_value': consumption
                })
        else:
            # Nouvel enregistrement
            record = ConsumptionRecord(
                start_time=start_time,
                end_time=end_time,
                consumption_kwh=consumption
            )
            session.add(record)

    # Commit tout ce qui n’est pas en conflit
    session.commit()

    return conflicts

def calculate_total_consumption(session: Session, start_dt, end_dt) -> float:
    """ Retourne la somme de la consommation sur la période [start_dt, end_dt). """
    total = session.query(
        func.sum(ConsumptionRecord.consumption_kwh)
    ).filter(
        ConsumptionRecord.start_time >= start_dt,
        ConsumptionRecord.start_time < end_dt
    ).scalar()

    return total if total else 0.0

def calculate_base_load(session: Session) -> float:
    """
    Exemple de calcul du talon sur l'ensemble de la base.
    """
    records = session.query(ConsumptionRecord.consumption_kwh).all()
    consumptions = [r[0] for r in records]
    if not consumptions:
        return 0.0
    consumptions.sort()
    index_5pct = int(len(consumptions) * 0.05)
    return consumptions[index_5pct]
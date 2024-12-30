from datetime import time

from sqlalchemy import create_engine, Column, Integer, Float, DateTime, Time, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class ConsumptionRecord(Base):
    __tablename__ = 'consumption'

    id = Column(Integer, primary_key=True, autoincrement=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    consumption_kwh = Column(Float, nullable=False)

class Settings(Base):
    __tablename__ = 'settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    hp_cost = Column(Float, nullable=False)
    hc_cost = Column(Float, nullable=False)
    hp_start = Column(Time, nullable=False)
    hp_end = Column(Time, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    solar_wc = Column(Float, nullable=False)
    solar_efficiency = Column(Float, nullable=False)
    solar_cost = Column(Float, nullable=False)

class Weather(Base):
    __tablename__ = 'weather'

    id = Column(Integer, primary_key=True, autoincrement=True)
    time = Column(DateTime, nullable=False, unique=True)
    shortwave_radiation = Column(Float, nullable=True)
    direct_radiation = Column(Float, nullable=True)
    direct_normal_irradiance = Column(Float, nullable=True)
    diffuse_radiation = Column(Float, nullable=True)
    temperature_2m = Column(Float, nullable=True)
    cloud_cover = Column(Float, nullable=True)
    wind_speed_10m = Column(Float, nullable=True)
    precipitation = Column(Float, nullable=True)

    __table_args__ = (UniqueConstraint('time', name='unique_time_weather'),)


def get_engine(db_path: str = "sqlite:///consumption.db"):
    engine = create_engine(db_path, echo=False)
    return engine

def create_tables(engine):
    Base.metadata.create_all(engine)

def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()

def get_or_create_settings(session):
    """
    Récupère les paramètres existants ou crée des valeurs par défaut.
    """
    settings = session.query(Settings).first()
    if not settings:
        # Crée des paramètres par défaut
        settings = Settings(
            hp_cost=0.27,
            hc_cost=0.2068,
            hp_start=time(7, 15),
            hp_end=time(23, 30),
            latitude=48.68,
            longitude=3.2199998,
            solar_wc=0,
            solar_efficiency=80.0,
            solar_cost=0.0,
        )
        session.add(settings)
        session.commit()
    return settings
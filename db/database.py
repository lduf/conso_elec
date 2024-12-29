from datetime import datetime, time

from sqlalchemy import create_engine, Column, Integer, Float, DateTime, Time
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
            hp_cost=0.20,
            hc_cost=0.15,
            hp_start=time(7, 0),
            hp_end=time(23, 0)
        )
        session.add(settings)
        session.commit()
    return settings
import os
import sys
from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, CheckConstraint, text, ForeignKey, func
from sqlalchemy.orm import declarative_base, sessionmaker

# 1. Setup Connection Configuration (with safe defaults)
user = os.getenv('DB_USER', 'postgres')
password = os.getenv('DB_PASSWORD', 'postgres')
db_name = os.getenv('DB_NAME', 'aero_hydra')
db_port = os.getenv('DB_PORT', '5432') # Use string first
db_host = os.getenv('DB_HOST', 'localhost')

db_url = f"postgresql://{user}:{password}@{db_host}:{db_port}/{db_name}"

# 2. Create the Engine and Session Factory
# These must be at the top level so dataCollector.py can import them
engine = create_engine(db_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Your Models ---
class TrackedAircraft(Base):
    __tablename__ = 'tracked_aircraft'
    icao24 = Column(String(6), primary_key=True)
    registration = Column(String(10), nullable=False)
    country = Column(String(50))
    owner = Column(String(100))
    payload_capacity_kg = Column(Integer)
    aircraft_model = Column(String(50))
    aircraft_type = Column(String(50))

    __table_args__ = (
        CheckConstraint(aircraft_type.in_(['airplane', 'helicopter']), name='type_check'),
    )

class FlightTelemetry(Base):
    __tablename__ = 'flight_telemetry'
    icao24 = Column(String(6), ForeignKey('tracked_aircraft.icao24'), primary_key=True)
    timestamp = Column(Integer, primary_key=True)
    lat = Column(Float)
    lon = Column(Float)
    baro_altitude = Column(Float)
    baro_altitude_ft = Column(Float)
    true_track = Column(Float)
    on_ground = Column(Boolean)
    
    speed_kph = Column(Float)
    vertical_speed_mmin = Column(Float)
    speed_kt = Column(Float)
    vertical_speed_ftmin = Column(Float)

    altitude_agl_ft = Column(Float)

    is_processed = Column(Boolean, default=False)

    is_low_pass = Column(Boolean, default=False)
    is_over_water = Column(Boolean, default=False)
    
class RegionOfInterest(Base):
    __tablename__ = "regions_of_interest"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    density = Column(Integer)  # Number of points found
    detected_at = Column(DateTime, default=func.now())


# --- Migration Logic ---
def run_migration():
    try:
        # Create all tables defined in Base
        Base.metadata.create_all(engine)
        print("\033[0;32m[INFO]\033[0m Database migration completed successfully.")
    except Exception as e:
        print(f"\033[0;31m[ERROR]\033[0m Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
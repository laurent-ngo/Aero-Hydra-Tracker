import os
import sys
from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, CheckConstraint, Text, ForeignKey, func, Numeric
from sqlalchemy.orm import declarative_base, sessionmaker
import logging
logger = logging.getLogger(__name__)

# 1. Setup Connection Configuration (with safe defaults)
user = os.getenv('DB_USER', 'neondb_owner')
password = os.getenv('DB_PASSWORD')
db_host = os.getenv('DB_HOST')
db_name = os.getenv('DB_NAME', 'neondb')
db_opts = os.getenv('DB_OPTIONS', 'sslmode=disable')

db_url = f"postgresql://{user}:{password}@{db_host}/{db_name}?{db_opts}"

# 2. Create the Engine and Session Factory
# These must be at the top level so dataCollector.py can import them
engine = create_engine(
    db_url,
    pool_pre_ping=True, 
    pool_recycle=3600
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class TrackedAircraft(Base):
    __tablename__ = 'tracked_aircraft'
    icao24 = Column(String(6), primary_key=True)
    registration = Column(String(10), nullable=False)
    country = Column(String(50))
    owner = Column(String(100))
    payload_capacity_kg = Column(Integer)
    aircraft_model = Column(String(50))
    aircraft_type = Column(String(50))
    sea_landing =Column(Boolean) 
    icon_id = Column(Integer)
    icon_size = Column(Integer)

    last_seen = Column(Integer)
    visible = Column(Boolean, nullable=False, default=True)
    active = Column(Boolean, nullable=False, default=True)

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
    
    is_full = Column(Boolean) 
    
    at_airfield = Column(Boolean, default=False)
    latest_airfield = Column(String(4), nullable=True)
    latest_waterfield = Column(String(4), nullable=True)

    # Country name, or sea/ocean name when over water — resolved daily, only for
    # the latest point of each aircraft. Left null on all other points.
    location = Column(String(100))

    source = Column(String(20), default='opensky', nullable=False)
    
class RegionOfInterest(Base):
    __tablename__ = "regions_of_interest"
    
    id = Column(Integer, primary_key=True, index=True)
    water_location_id = Column(Integer, ForeignKey('water_locations.id'), nullable=True)
    name = Column(String, nullable=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    geometry = Column(Text, nullable=True)
    
    type = Column(String(50))
    
    density = Column(Integer)  # Number of points found
    detected_at = Column(DateTime, default=func.now())
    level = Column(Integer)

    
    __table_args__ = (
        CheckConstraint(type.in_(['water', 'training']), name='type_check'),
    )

class Airfield(Base):
    __tablename__ = 'airfields'

    id = Column(Integer, primary_key=True)
    icao = Column(String(4), unique=True)
    name = Column(String)
    lat = Column(Float)
    lon = Column(Float)

class WaterLocation(Base):
    __tablename__ = 'water_locations'

    id  = Column(Integer, primary_key=True)
    ref = Column(String(4), unique=True)
    name = Column(String)
    lat = Column(Float)
    lon = Column(Float)

class FirmsFireIncident(Base):
    __tablename__ = 'firms_fire_incident'

    id             = Column(Integer, primary_key=True, autoincrement=True)
    first_detected = Column(String(10))   # YYYY-MM-DD
    last_detected  = Column(String(10))   # YYYY-MM-DD
    status         = Column(String(10), default='active')  # active / closed
    perimeter      = Column(Text)         # GeoJSON polygon (union of hotspots + buffer)
    centroid_lat   = Column(Float)
    centroid_lon   = Column(Float)
    area_ha        = Column(Float)
    buffer_km      = Column(Float, default=1.0)
    hotspot_count  = Column(Integer, default=0)
    max_frp        = Column(Float)        # max fire radiative power across all hotspots


class FirmsHotspot(Base):
    __tablename__ = 'firms_hotspot'

    id         = Column(Integer, primary_key=True, autoincrement=True)
    source_id  = Column(String(100), unique=True)  # dedup key
    fire_id    = Column(Integer, ForeignKey('firms_fire_incident.id'), nullable=True)

    acq_date   = Column(String(10))   # YYYY-MM-DD
    acq_time   = Column(String(4))    # HHMM
    lat        = Column(Float)
    lon        = Column(Float)
    scan_km    = Column(Float)        # pixel width  (from FIRMS scan field)
    track_km   = Column(Float)        # pixel height (from FIRMS track field)
    confidence = Column(String(20))   # 'low'/'nominal'/'high' (VIIRS) or 0-100 (MODIS)
    frp        = Column(Float)        # fire radiative power MW
    satellite  = Column(String(20))
    instrument = Column(String(20))
    geometry   = Column(Text)         # GeoJSON of buffered pixel footprint
    fetched_at = Column(Integer)      # unix timestamp


# --- Migration Logic ---
def run_migration():
    try:
        # Create all tables defined in Base
        Base.metadata.create_all(engine)
        logger.info("Database migration completed successfully.")
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()

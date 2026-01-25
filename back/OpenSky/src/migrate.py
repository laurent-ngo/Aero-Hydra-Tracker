import os
import sys
from sqlalchemy import create_engine, Column, String, Integer, DateTime, CheckConstraint, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

# Import your color helpers if you decide to make a python version, 
# but for now, we'll use simple prints.
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

    __table_args__ = (
        CheckConstraint(aircraft_type.in_(['airplane', 'helicopter']), name='type_check'),
    )

def run_migration():
    # Construct Connection String
    user = os.getenv('DB_USER')
    password = os.getenv('DB_PASSWORD')
    db_name = os.getenv('DB_NAME')
    db_port = os.getenv('DB_PORT')
    
    # Use 'localhost' for WSL2 to Docker, or 'db' if running inside Docker
    db_url = f"postgresql://{user}:{password}@localhost:{db_port}/{db_name}"
    
    try:
        engine = create_engine(db_url)
        # Create all tables defined in Base
        Base.metadata.create_all(engine)
        print("[INFO] Database migration completed successfully.")
    except Exception as e:
        print(f"[ERROR] Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_migration()
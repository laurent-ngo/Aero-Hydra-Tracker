import os
import sys
import csv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from migrate import TrackedAircraft, Airfield
import logging
logger = logging.getLogger(__name__)

def load_aircrafts_from_csv(file_path):

    user = os.getenv('DB_USER', 'neondb_owner')
    password = os.getenv('DB_PASSWORD')
    db_host = os.getenv('DB_HOST')
    db_name = os.getenv('DB_NAME', 'neondb')
    db_opts = os.getenv('DB_OPTIONS', 'sslmode=require')

    db_url = f"postgresql://{user}:{password}@{db_host}/{db_name}?{db_opts}"
    
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        with open(file_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            new_records = 0
            skipped_records = 0

            for row in reader:
                icao_id = row['icao24'].lower().strip()
                
                # Check if this ID already exists in the table
                exists = session.query(TrackedAircraft).filter_by(icao24=icao_id).first()
                
                if not exists:
                    aircraft = TrackedAircraft(
                        icao24=icao_id,
                        registration=row['registration'].strip(),
                        country=row['country'].strip(),
                        owner=row['owner'].strip(),
                        payload_capacity_kg=int(row['payload_capacity_kg']),
                        aircraft_type=row['aircraft_type'].strip(),
                        aircraft_model=row['aircraft_model'].strip()
                    )
                    session.add(aircraft)
                    new_records += 1
                else:
                    skipped_records += 1
            
            session.commit()
            logger.info(f"Load complete: {new_records} added, {skipped_records} already existed.")
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to load CSV: {e}")
    finally:
        session.close()

def load_airfields_from_csv(file_path):

    user = os.getenv('DB_USER', 'neondb_owner')
    password = os.getenv('DB_PASSWORD')
    db_host = os.getenv('DB_HOST')
    db_name = os.getenv('DB_NAME', 'neondb')
    db_opts = os.getenv('DB_OPTIONS', 'sslmode=require')

    db_url = f"postgresql://{user}:{password}@{db_host}/{db_name}?{db_opts}"
    
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        with open(file_path, mode='r', encoding='utf-8') as f:
            # Using DictReader to map columns by name
            reader = csv.DictReader(f)
            new_records = 0
            skipped_records = 0

            for row in reader:
                # Cleaning the ICAO code
                icao_code = row['icao'].upper().strip()
                
                # Check for existing record to avoid unique constraint errors
                exists = session.query(Airfield).filter_by(icao=icao_code).first()
                
                if not exists:
                    # Strip keys in case of trailing spaces in CSV header like 'lat '
                    airfield = Airfield(
                        name=row['name'].strip(),
                        icao=icao_code,
                        lat=float(row['lat'].strip()),
                        lon=float(row['lon'].strip())
                    )
                    session.add(airfield)
                    new_records += 1
                else:
                    skipped_records += 1
            
            session.commit()
            logger.info(f"Airfields complete: {new_records} added, {skipped_records} already existed.")
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to load Airfields CSV: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    # Check if argument is provided
    if len(sys.argv) < 3:
        logger.warning("Usage: python3 loadCSV.py <aircrafts.csv> <airfields.csv>")
        sys.exit(1)
    
    load_aircrafts_from_csv(sys.argv[1])
    load_airfields_from_csv(sys.argv[2])
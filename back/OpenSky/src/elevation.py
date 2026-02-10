import math
import migrate
import requests
import os
import time
import logging
logger = logging.getLogger(__name__)

from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker

user = os.getenv('DB_USER', 'postgres')
password = os.getenv('DB_PASSWORD', 'postgres')
db_host = os.getenv('DB_HOST', 'localhost:5432')

db_url = f"postgresql://{user}:{password}@{db_host}"

# --- Database Setup ---
engine = create_engine(db_url)
Session = sessionmaker(bind=engine)
db = Session()

def get_ground_elevation(lat, lon):
    try:
        # Using the Open-Elevation public API
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}"
        response = requests.get(url, timeout=5)
        data = response.json()
        # Returns elevation in meters
        
        time.sleep(0.5) 
        return data['results'][0]['elevation']
    except Exception as e:
        logger.error(f"Elevation lookup failed: {e}")
        return None # Default to sea level if lookup fails
    
def get_or_fetch_elevation(lat, lon):
    """
    Checks the local DB for ground elevation at a 3-decimal precision grid.
    If not found, calls the API and saves the result.
    """
    grid_lat = round(float(lat), 3)
    grid_lon = round(float(lon), 3)

    # 1. Check local cache
    cached = db.query(migrate.GroundElevation).filter_by(
        latitude=grid_lat, 
        longitude=grid_lon
    ).first()

    if cached:
        logger.debug( 'Elevation found in DB')
        return cached.elevation_m

    # 2. Cache Miss: Call the limited API

    elevation = get_ground_elevation(grid_lat, grid_lon)
    
    if elevation is not None:
        # 3. Store in DB
        new_elevation = migrate.GroundElevation(
            latitude=grid_lat,
            longitude=grid_lon,
            elevation_m=elevation
        )
        db.add(new_elevation)
        db.commit()
        
        logger.debug( 'Elevation collected from API and saved in DB')
        return elevation
        
    return None
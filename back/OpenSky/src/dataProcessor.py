import os
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from math import radians, cos, sin, asin, sqrt
import requests
import migrate # Your model file

user = os.getenv('DB_USER', 'postgres')
password = os.getenv('DB_PASSWORD', 'postgres')
db_name = os.getenv('DB_NAME', 'aero_hydra')
db_port = os.getenv('DB_PORT', '5432') # Use string first
db_host = os.getenv('DB_HOST', 'localhost')

db_url = f"postgresql://{user}:{password}@{db_host}:{db_port}/{db_name}"

# --- Database Setup ---
engine = create_engine(db_url)
Session = sessionmaker(bind=engine)
db = Session()


''' 
    Haversine: 
    formula calculates the shortest distance (great-circle distance) 
    between two points on a sphere, like Earth.
'''
def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 6371 * 2 * asin(sqrt(a))

def backfill_telemetry():
    # 1. Get all unique ICAO24s that have empty speed data
    aircraft_ids = db.query(migrate.FlightTelemetry.icao24).filter(
        migrate.FlightTelemetry.speed_kph == None
    ).distinct().all()

    for (icao,) in aircraft_ids:
        print(f"Processing aircraft: {icao}")
        
        # 2. Get all points for this aircraft, oldest first
        points = db.query(migrate.FlightTelemetry).filter(
            migrate.FlightTelemetry.icao24 == icao
        ).order_by(migrate.FlightTelemetry.timestamp.asc()).all()

        for i in range(1, len(points)):
            curr = points[i]
            prev = points[i-1]

            time_diff = curr.timestamp - prev.timestamp

            # 3. Logic: 
            if  curr.speed_kph is None:
                
                hours = time_diff / 3600
                minutes = time_diff / 60

                # Horizontal Speed
                dist_km = haversine(prev.lon, prev.lat, curr.lon, curr.lat)
                curr.speed_kph = round(dist_km / hours, 2)
                curr.speed_kt = round(curr.speed_kph * 0.539957, 2)

                # Vertical Speed
                if curr.baro_altitude is not None and prev.baro_altitude is not None:
                    alt_diff_m = curr.baro_altitude - prev.baro_altitude
                    curr.vertical_speed_mmin = round(alt_diff_m / minutes, 2)
                    curr.vertical_speed_ftmin = round(curr.vertical_speed_mmin * 3.28084, 0)
        
        # Commit per aircraft to keep memory usage low
        db.commit()
    print("Backfill complete!")


def get_ground_elevation(lat, lon):
    try:
        # Using the Open-Elevation public API
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}"
        response = requests.get(url, timeout=5)
        data = response.json()
        # Returns elevation in meters
        return data['results'][0]['elevation']
    except Exception as e:
        print(f"Elevation lookup failed: {e}")
        return 0 # Default to sea level if lookup fails

def backfill_agl():
    # 1. Fetch only records that have baro_altitude but missing AGL
    # We process in batches to be gentle on the API and memory
    points_to_fix = db.query(migrate.FlightTelemetry).filter(
        migrate.FlightTelemetry.baro_altitude != None,
        migrate.FlightTelemetry.altitude_agl_ft == None
    ).limit(500).all() # Processing 500 at a time is safer

    if not points_to_fix:
        print("No pending AGL calculations found.")
        return

    print(f"Calculating AGL for {len(points_to_fix)} points...")

    for p in points_to_fix:
        # 2. Get the ground height from your new method
        ground_m = get_ground_elevation(p.lat, p.lon)
        
        if ground_m is not None:
            # 3. Calculation: MSL - Ground = AGL
            agl_m = p.baro_altitude - ground_m
            p.altitude_agl_ft = round(agl_m * 3.28084, 0)
            
            time.sleep(0.5) 

    db.commit()
    print("Batch AGL backfill complete.")
    

def label_low_passes(db_session, threshold_ft=500):
    # Only process points where AGL has already been calculated
    points = db_session.query(migrate.FlightTelemetry).filter(
        migrate.FlightTelemetry.altitude_agl_ft != None,
        migrate.FlightTelemetry.is_low_pass == False # Only check unlabelled
    ).all()

    if not points:
        print("No new points to label for low passes.")
        return

    count = 0
    for p in points:
        # If the plane is below our threshold (e.g. 500ft AGL)
        # and specifically NOT on the ground (if your data has that flag)
        if p.altitude_agl_ft <= threshold_ft and p.altitude_agl_ft > 10:
            p.is_low_pass = True
            count += 1
            
    db_session.commit()
    print(f"Labeling complete: {count} points identified as low pass.")

if __name__ == "__main__":
    backfill_telemetry()
    backfill_agl()
    label_low_passes()
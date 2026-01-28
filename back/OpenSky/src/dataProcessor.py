import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from math import radians, cos, sin, asin, sqrt
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

if __name__ == "__main__":
    backfill_telemetry()
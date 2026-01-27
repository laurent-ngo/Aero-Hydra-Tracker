from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from migrate import FlightTelemetry, TrackedAircraft


def get_all_tracked_icao24(session):
    """
    Returns a list of all icao24 strings currently in the tracked_aircraft table.
    """
    try:
        # We query only the icao24 column to keep it fast
        results = session.query(TrackedAircraft.icao24).all()
        
        # SQLAlchemy returns a list of tuples like [('3b7b70',), ('43c6f3',)]
        # We flatten it into a simple list of strings
        return [r[0] for r in results]
        
    except Exception as e:
        print(f"\033[0;31m[ERROR]\033[0m Failed to fetch tracked aircraft list: {e}")
        return []
    
def get_latest_timestamp(session, icao_code):
    """
    Returns the most recent timestamp for a given icao24.
    Returns -1 if no data exists.
    """
    # Force lowercase to match DB standards
    icao_code = icao_code.lower().strip()
    
    # Query for the maximum timestamp
    result = session.query(func.max(FlightTelemetry.timestamp))\
                    .filter(FlightTelemetry.icao24 == icao_code)\
                    .scalar()
    
    return result if result is not None else -1

def sync_flight_data(session, icao_code, raw_path_data):
    """
    Filters out old waypoints and inserts only the new ones.
    """
    # 1. Get the current 'checkpoint' from the DB
    latest_ts = get_latest_timestamp(session, icao_code)
    
    # 2. Filter waypoints (assuming point[0] is the timestamp)
    # Only keep points where timestamp > latest_ts
    new_points = [p for p in raw_path_data if p[0] > latest_ts]
    
    if not new_points:
        print(f"\033[1;34m[INFO]\033[0m No new data to load for {icao_code}.")
        return

    # 3. Perform the bulk insert from the previous step
    # (Using the bulk_insert_telemetry function we wrote earlier)
    bulk_insert_telemetry(session, icao_code, new_points)
    print(f"\033[0;32m[SUCCESS]\033[0m Added {len(new_points)} new waypoints.")


def bulk_insert_telemetry(session, icao24, path_data):
    """
    Inserts a list of waypoints in a single transaction.
    If a timestamp+icao24 already exists, it does nothing (prevents duplicates).
    """
    if not path_data:
        return

    # 1. Transform the raw OpenSky list into a list of dictionaries
    values = [
        {
            "icao24": icao24,
            "timestamp": p[0],
            "lat": p[1],
            "lon": p[2],
            "baro_altitude": p[3],
            "true_track": p[4],
            "on_ground": p[5]
        }
        for p in path_data
    ]

    # 2. Create the 'ON CONFLICT DO NOTHING' statement
    # index_elements must match your Primary Key (icao24 + timestamp)
    stmt = insert(FlightTelemetry).values(values)
    stmt = stmt.on_conflict_do_nothing(index_elements=['icao24', 'timestamp'])

    try:
        session.execute(stmt)
        session.commit()
        print(f"\033[0;32m[INFO]\033[0m Bulk insert complete. Processed {len(values)} points.")
    except Exception as e:
        session.rollback() # Diplomatic cleanup if things go wrong
        print(f"\033[0;31m[ERROR]\033[0m Bulk insert failed: {e}")
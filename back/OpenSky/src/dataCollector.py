import os
import time
import argparse
import sys
from migrate import SessionLocal
from openSkyCollector import FirefleetCollector
from aircraftDataHandler import (
    get_all_tracked_icao24, 
    get_latest_timestamp, 
    bulk_insert_telemetry
)

def orchestrate_sync(active_only=False):
    TOKEN = os.getenv('OPENSKY_CLIENT_TOKEN')
    collector = FirefleetCollector(TOKEN)
    session = None
    
    try:
        session = SessionLocal()
        icao_list = get_all_tracked_icao24(session, active_only)
        
        if len(icao_list) < 1:
            print(f"[INFO] No active aircraft...")

        print(f"[START] Syncing fleet of {len(icao_list)} aircrafts...")


        for icao in icao_list:
            # 1. Get high-water mark
            last_ts = get_latest_timestamp(session, icao)
            
            # 2. Fetch track
            track_data = collector.get_aircraft_track(icao)

            if track_data and 'path' in track_data:
                # 3. Filter and Insert
                new_points = [p for p in track_data['path'] if p[0] > last_ts]
                
                if new_points:
                    bulk_insert_telemetry(session, icao, new_points)
                    print(f"[{icao}] Inserted {len(new_points)} new points.")
                else:
                    print(f"[{icao}] Up-to-date.")
            else:
                print(f"[{icao}] No live data available.")
            
            # 4. API Throttling
            time.sleep(0.5)

        print("[DONE] Fleet sync completed successfully.")

    except Exception as e:
        print(f"[CRITICAL] Orchestrator failed: {e}")
    finally:
        if session:
            session.close()
            print("[INFO] Database session closed.")

if __name__ == "__main__":
    # 1. Setup the argument parser
    parser = argparse.ArgumentParser(description="AERO-HYDRA Sync Orchestrator")
    
    # 2. Add the toggle (action="store_true" means it's False by default)
    parser.add_argument(
        "--active", 
        action="store_true", 
        help="Only sync aircraft active in the last 5 minutes"
    )

    args = parser.parse_args()

    # 3. Pass the argument to your function
    orchestrate_sync(active_only=args.active)
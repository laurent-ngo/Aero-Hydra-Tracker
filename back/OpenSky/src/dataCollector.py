import os
import time
from tqdm import tqdm
import time
from migrate import SessionLocal
from openSkyCollector import FirefleetCollector
from aircraftDataHandler import (
    get_all_tracked_icao24, 
    get_latest_timestamp, 
    bulk_insert_telemetry
)


def orchestrate_sync():
    # 1. Setup
    TOKEN = os.getenv('OPENSKY_CLIENT_TOKEN')
    collector = FirefleetCollector(TOKEN)
    
    # Initialize session here so 'finally' can see it
    session = None
    
    try:
        session = SessionLocal() # Now we assign the actual connection

        icao_list = get_all_tracked_icao24(session)
         
        # We wrap the list in tqdm for a visual progress bar
        # 'desc' sets the label on the left, 'unit' sets the label on the right
        pbar = tqdm(icao_list, desc="Syncing Fleet", unit="plane", colour="green")

        for icao in pbar:
            # Update the bar's description dynamically with the current ICAO
            pbar.set_description(f"Syncing {icao}")

            # 1. Get high-water mark to filter duplicates later
            last_ts = get_latest_timestamp(session, icao)
            
            # 2. Call get_aircraft_track directly
            # This returns the full current track for the aircraft
            track_data = collector.get_aircraft_track(icao)

            if track_data and 'path' in track_data:
                # 3. Filter: Only keep points newer than what we have
                new_points = [p for p in track_data['path'] if p[0] > last_ts]
                
                if new_points:
                    bulk_insert_telemetry(session, icao, new_points)
                    pbar.set_postfix({"new_pts": len(new_points)})
                else:
                    pbar.set_postfix({"status": "up-to-date"})
            else:
                pbar.set_postfix({"status": "no live data"})
            
            # 4. Delay for the API
            time.sleep(0.5)

        print("\n\033[1;32m[DONE]\033[0m Fleet sync completed successfully.")

    except Exception as e:
        print(f"\033[1;31m[CRITICAL]\033[0m Orchestrator failed: {e}")
    finally:
        # Only try to close if the session was actually created
        if session:
            session.close()
            print("\033[0;34m[INFO]\033[0m Database session closed.")

if __name__ == "__main__":
    orchestrate_sync()
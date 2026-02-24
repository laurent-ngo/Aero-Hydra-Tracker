import os
import time
import argparse
import sys
import logging
logger = logging.getLogger(__name__)

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
        full_db_icao_list = get_all_tracked_icao24(session, active_only)

        full_icao_list = collector.get_by_icao24(full_db_icao_list)

        if active_only:
            EXCLUDED_ICAO = {"3b7b64", "3b7b65", "3b7b66"}
            icao_list = [icao for icao in full_icao_list if icao not in EXCLUDED_ICAO]
        else:
            icao_list = full_icao_list

        if len(icao_list) < 1:
            logger.info("No active aircraft...")

        logger.info(f"Syncing fleet of {len(icao_list)} aircrafts...")


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
                    logger.info(f"[{icao}] Inserted {len(new_points)} new points.")
                else:
                    logger.debug(f"[{icao}] Up-to-date.")
            else:
                logger.debug(f"[{icao}] No live data available.")
            
            # 4. API Throttling
            time.sleep(0.5)

        logger.info("[DONE] Fleet sync completed successfully.")
        return icao_list

    except Exception as e:
        logger.critical(f"Orchestrator failed: {e}")
    finally:
        if session:
            session.close()
            logger.info("Database session closed.")

if __name__ == "__main__":

    log_level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"
    DATE_FORMAT = "%H:%M:%S"

    logging.basicConfig(
        level=log_level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

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
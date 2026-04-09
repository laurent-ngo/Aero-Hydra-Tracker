import os
import time
import argparse
import sys
import logging
import json
logger = logging.getLogger(__name__)

from migrate import SessionLocal
from concurrent.futures import ThreadPoolExecutor
from openSkyCollector import FirefleetCollector, AdsbV2Collector

from aircraftDataHandler import (
    get_all_tracked_icao24, 
    get_latest_timestamp, 
    bulk_insert_telemetry
)

CACHE_FILE = "tracked_icao_cache.json"

def orchestrate_sync():
    TOKEN = os.getenv('OPENSKY_CLIENT_TOKEN')
    collector     = FirefleetCollector(TOKEN)
    supplementary = [
        AdsbV2Collector('adsbfi'),
        AdsbV2Collector('airplaneslive'),
        AdsbV2Collector('adsbonelol'),
    ]
    session = None
    
    try:
        session = SessionLocal()

        # Load tracked ICAO list
        full_db_icao_list = None
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    full_db_icao_list = json.load(f)
                logger.info("Loaded tracked ICAOs from local cache.")
            except Exception as e:
                logger.error(f"Cache read failed: {e}")
        if full_db_icao_list is None:
            full_db_icao_list = get_all_tracked_icao24(session, False)
            try:
                with open(CACHE_FILE, 'w') as f:
                    json.dump(full_db_icao_list, f)
                logger.info("Saved tracked ICAOs to local cache.")
            except Exception as e:
                logger.warning(f"Could not write cache file: {e}")

        full_icao_list_dict = collector.get_by_icao24(full_db_icao_list)
        icao_list = [ac['icao24'] for ac in full_icao_list_dict]

        if len(icao_list) < 1:
            logger.info("No active aircraft...")

        # Fetch all supplementary sources in parallel, merge keeping freshest per icao24
        with ThreadPoolExecutor() as ex:
            all_results = list(ex.map(lambda s: s.get_by_icao24(full_db_icao_list), supplementary))

        merged_supplementary = {}
        for source_results in all_results:
            for icao24, data in source_results.items():
                if icao24 not in merged_supplementary or data['timestamp'] > merged_supplementary[icao24]['timestamp']:
                    merged_supplementary[icao24] = data

        logger.info(f"Syncing fleet of {len(icao_list)} aircrafts...")
        for icao in icao_list:
            last_ts = get_latest_timestamp(session, icao)

            # OpenSky track
            track_data = collector.get_aircraft_track(icao)
            if track_data and 'path' in track_data:
                new_points = [p for p in track_data['path'] if p[0] > last_ts]
                if new_points:
                    bulk_insert_telemetry(session, icao, new_points)
                    logger.info(f"[{icao}] Inserted {len(new_points)} new points.")
                    last_ts = max(p[0] for p in new_points)
                else:
                    logger.debug(f"[{icao}] Up-to-date.")
            else:
                logger.debug(f"[{icao}] No live data available.")

            # Supplementary sources — only insert if timestamp is newer
            if icao in merged_supplementary:
                sup = merged_supplementary[icao]
                if sup['timestamp'] > last_ts:
                    sup_alt_m = round(sup['baro_alt'] / 3.28084, 1) if sup['baro_alt'] not in (None, 'ground') else None
                    bulk_insert_telemetry(session, icao, [[sup['timestamp'], sup['lat'], sup['lon'], sup_alt_m, sup['true_track'], sup['on_ground']]])
                    logger.info(f"[{icao}] Inserted 1 supplementary point (ts={sup['timestamp']}).")
                else:
                    logger.debug(f"[{icao}] Supplementary point already covered.")

            time.sleep(0.5)

        logger.info("[DONE] Fleet sync completed successfully.")
        return icao_list

    except Exception as e:
        logger.critical(f"Orchestrator failed: {e}")
        raise
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

    # 3. Pass the argument to your function
    orchestrate_sync()
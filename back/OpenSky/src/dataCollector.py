import os
import time
import argparse
import sys
import logging
import json
logger = logging.getLogger(__name__)

from migrate import SessionLocal
from concurrent.futures import ThreadPoolExecutor
from openSkyCollector import FirefleetCollector, AdsbV2Collector, FR24Collector

from aircraftDataHandler import (
    get_all_tracked_icao24, 
    get_latest_timestamp, 
    bulk_insert_telemetry
)

CACHE_FILE = "tracked_icao_cache.json"
ADSB_CACHE_FILE = "adsb_supplement_cache.json"


def update_adsb_cache():
    """Fetch from all supplementary sources and store new points in cache."""
    supplementary = [
        AdsbV2Collector('adsbfi'),
        AdsbV2Collector('airplaneslive'),
        AdsbV2Collector('adsbonelol'),
        AdsbV2Collector('adsboneapi'),
    ]

    full_db_icao_list = get_cached_icao_list()

    # Fetch all sources in parallel, merge keeping freshest per icao24
    with ThreadPoolExecutor() as ex:
        all_results = list(ex.map(lambda s: s.get_by_icao24(full_db_icao_list), supplementary))

    merged = {}
    for source_results in all_results:
        for icao24, data in source_results.items():
            if icao24 not in merged or data['timestamp'] > merged[icao24]['timestamp']:
                merged[icao24] = data

    if not merged:
        logger.info("ADSB cache update: no data returned.")
        return

    # Load existing cache
    cache = {}
    if os.path.exists(ADSB_CACHE_FILE):
        try:
            with open(ADSB_CACHE_FILE, 'r') as f:
                cache = json.load(f)
        except Exception as e:
            logger.warning(f"Could not read ADSB cache: {e}")

    # Add new points — one entry per timestamp per icao24
    new_count = 0
    for icao24, data in merged.items():
        ts = str(data['timestamp'])
        if icao24 not in cache:
            cache[icao24] = {}
        if ts not in cache[icao24]:
            cache[icao24][ts] = {
                'lat':       data['lat'],
                'lon':       data['lon'],
                'baro_alt':  data['baro_alt'],
                'on_ground': data['on_ground'],
                'true_track':data['true_track'],
                'source':    data['source'],
            }
            new_count += 1

    # Write back
    with open(ADSB_CACHE_FILE, 'w') as f:
        json.dump(cache, f)

    logger.info(f"ADSB cache updated: {new_count} new points cached.")

def get_cached_icao_list():
    full_db_icao_list = None
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                full_db_icao_list = json.load(f)
            logger.info("Loaded tracked ICAOs from local cache.")
        except Exception as e:
            logger.error(f"Cache read failed: {e}")
    return full_db_icao_list

def orchestrate_sync():
    TOKEN = os.getenv('OPENSKY_CLIENT_TOKEN')
    collector = FirefleetCollector(TOKEN)
    session   = None

    try:
        session = SessionLocal()

        # Load tracked ICAO list
        full_db_icao_list = get_cached_icao_list()

        if full_db_icao_list is None:
            full_db_icao_list = get_all_tracked_icao24(session, False)
            try:
                with open(CACHE_FILE, 'w') as f:
                    json.dump(full_db_icao_list, f)
                logger.info("Saved tracked ICAOs to local cache.")
            except Exception as e:
                logger.warning(f"Could not write cache file: {e}")

        # OpenSky — bbox-filtered, only active aircraft
        full_icao_list_dict = collector.get_by_icao24(full_db_icao_list)
        opensky_active = {ac['icao24'] for ac in full_icao_list_dict}

        if len(opensky_active) < 1:
            logger.info("No active aircraft in OpenSky...")

        # Load ADSB supplement cache
        adsb_cache = {}
        if os.path.exists(ADSB_CACHE_FILE):
            try:
                with open(ADSB_CACHE_FILE, 'r') as f:
                    adsb_cache = json.load(f)
                logger.info(f"Loaded ADSB cache with {sum(len(v) for v in adsb_cache.values())} points.")
            except Exception as e:
                logger.warning(f"Could not read ADSB cache: {e}")

        logger.info(f"Syncing full fleet of {len(full_db_icao_list)} aircrafts (OpenSky active: {len(opensky_active)})...")

        for icao in full_db_icao_list:
            last_ts = get_latest_timestamp(session, icao)
            opensky_timestamps = set()

            # OpenSky track — only for bbox-visible aircraft
            if icao in opensky_active:
                track_data = collector.get_aircraft_track(icao)
                if track_data and 'path' in track_data:
                    new_points = [p for p in track_data['path'] if p[0] > last_ts]
                    if new_points:
                        bulk_insert_telemetry(session, icao, new_points)
                        logger.info(f"[{icao}] Inserted {len(new_points)} new points.")
                        last_ts = max(p[0] for p in new_points)
                        opensky_timestamps = {p[0] for p in track_data['path']}
                    else:
                        logger.debug(f"[{icao}] Up-to-date.")
                else:
                    logger.debug(f"[{icao}] No live data available.")

            # ADSB cache — all aircraft regardless of bbox
            if icao in adsb_cache:
                cached_points = adsb_cache[icao]
                inserted = 0
                for ts_str, point in sorted(cached_points.items(), key=lambda x: int(x[0])):
                    ts = int(ts_str)
                    if ts in opensky_timestamps or ts <= last_ts:
                        continue
                    sup_alt_m = round(point['baro_alt'] / 3.28084, 1) if point['baro_alt'] not in (None, 'ground') else None
                    bulk_insert_telemetry(session, icao, [[
                        ts,
                        point['lat'],
                        point['lon'],
                        sup_alt_m,
                        point['true_track'],
                        point['on_ground'],
                    ]], source=point['source'])
                    inserted += 1
                if inserted:
                    logger.info(f"[{icao}] Inserted {inserted} cached ADSB points.")

            time.sleep(0.5)

        # Clear the cache after successful merge
        if os.path.exists(ADSB_CACHE_FILE):
            os.remove(ADSB_CACHE_FILE)
            logger.info("ADSB cache cleared after merge.")

        logger.info("[DONE] Fleet sync completed successfully.")
        # Return union of OpenSky active + any icao that had cached ADSB points inserted
        adsb_inserted = {icao for icao in full_db_icao_list if icao in adsb_cache}
        return list(set(opensky_active) | adsb_inserted)


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
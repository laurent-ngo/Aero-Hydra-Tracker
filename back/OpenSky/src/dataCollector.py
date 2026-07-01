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

CACHE_FILE      = "tracked_icao_cache.json"
ADSB_CACHE_FILE = "adsb_supplement_cache.json"
FR24_CACHE_FILE = "fr24_cache.json"


def _info_score(point):
    """
    Count how many meaningful fields are populated in a data point.
    Used to prefer richer points when two sources report the same (icao24, timestamp).
    Fields checked: lat, lon, baro_alt, on_ground, true_track.
    """
    return sum(1 for f in ('lat', 'lon', 'baro_alt', 'true_track')
               if point.get(f) is not None)

def _cache_point_score(cp):
    """Same score for a point already stored in the cache dict format."""
    return sum(1 for f in ('lat', 'lon', 'baro_alt', 'true_track')
               if cp.get(f) is not None)

def update_adsb_cache():
    """Fetch from all supplementary sources and store new points in cache."""
    supplementary = [
        AdsbV2Collector('adsbfi'),
        AdsbV2Collector('airplaneslive'),
        AdsbV2Collector('adsbonelol'),
        AdsbV2Collector('adsboneapi'),
    ]

    full_db_icao_list = get_cached_icao_list()

    # Fetch all sources in parallel, merge keeping freshest per icao24.
    # On equal timestamps, keep the point with more populated fields.
    with ThreadPoolExecutor() as ex:
        all_results = list(ex.map(lambda s: s.get_by_icao24(full_db_icao_list), supplementary))

    merged = {}
    for source_results in all_results:
        for icao24, data in source_results.items():
            if icao24 not in merged:
                merged[icao24] = data
            elif data['timestamp'] > merged[icao24]['timestamp']:
                merged[icao24] = data
            elif data['timestamp'] == merged[icao24]['timestamp'] and _info_score(data) > _info_score(merged[icao24]):
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

    # Add new points — one entry per timestamp per icao24.
    # On collision, keep whichever point has more populated fields.
    new_count = updated_count = 0
    for icao24, data in merged.items():
        ts = str(data['timestamp'])
        if icao24 not in cache:
            cache[icao24] = {}

        incoming = {
            'lat':        data['lat'],
            'lon':        data['lon'],
            'baro_alt':   data['baro_alt'],
            'on_ground':  data['on_ground'],
            'true_track': data['true_track'],
            'source':     data['source'],
        }

        if ts not in cache[icao24]:
            cache[icao24][ts] = incoming
            new_count += 1
        elif _info_score(incoming) > _cache_point_score(cache[icao24][ts]):
            cache[icao24][ts] = incoming
            updated_count += 1

    # Write back
    with open(ADSB_CACHE_FILE, 'w') as f:
        json.dump(cache, f)

    logger.info(f"ADSB cache updated: {new_count} new points, {updated_count} replaced with richer data.")

def update_fr24_cache():
    """Query FR24 for the full fleet and cache which aircraft are currently active."""
    fr24 = FR24Collector() if os.getenv('FR24_API_KEY') else None
    if not fr24:
        logger.info("FR24 cache: no API key configured, skipping.")
        return

    session = None
    try:
        session = SessionLocal()
        from migrate import TrackedAircraft
        rows = session.query(TrackedAircraft.icao24, TrackedAircraft.registration).all()
        reg_to_icao = {r.registration: r.icao24.lower() for r in rows if r.registration}
    finally:
        if session:
            session.close()

    if not reg_to_icao:
        logger.info("FR24 cache: no tracked aircraft with registrations.")
        return

    results = fr24.get_by_registrations(reg_to_icao)

    if results:
        with open(FR24_CACHE_FILE, 'w') as f:
            json.dump(results, f)
        logger.info(f"FR24 cache updated: {len(results)} active aircraft.")
    else:
        if os.path.exists(FR24_CACHE_FILE):
            os.remove(FR24_CACHE_FILE)
        logger.info("FR24 cache: no active aircraft.")


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
    fr24      = FR24Collector() if os.getenv('FR24_API_KEY') else None
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

        # OpenSky — bbox-filtered live fetch
        full_icao_list_dict = collector.get_by_icao24(full_db_icao_list)
        opensky_active = {ac['icao24'] for ac in full_icao_list_dict}

        # FR24 — read from cache populated by update_fr24_cache()
        fr24_cache = {}
        if os.path.exists(FR24_CACHE_FILE):
            try:
                with open(FR24_CACHE_FILE, 'r') as f:
                    fr24_cache = json.load(f)
                logger.info(f"Loaded FR24 cache: {len(fr24_cache)} active aircraft.")
            except Exception as e:
                logger.warning(f"Could not read FR24 cache: {e}")
        fr24_active = set(fr24_cache.keys())

        if not opensky_active:
            logger.info("No active aircraft in OpenSky...")
        if fr24 and not fr24_active:
            logger.info("No active aircraft in FR24...")

        # Load ADSB supplement cache
        adsb_cache = {}
        if os.path.exists(ADSB_CACHE_FILE):
            try:
                with open(ADSB_CACHE_FILE, 'r') as f:
                    adsb_cache = json.load(f)
                logger.info(f"Loaded ADSB cache with {sum(len(v) for v in adsb_cache.values())} points.")
            except Exception as e:
                logger.warning(f"Could not read ADSB cache: {e}")

        logger.info(f"Syncing full fleet of {len(full_db_icao_list)} aircraft (OpenSky: {len(opensky_active)}, FR24: {len(fr24_active)})...")

        for icao in full_db_icao_list:
            last_ts = get_latest_timestamp(session, icao)

            # OpenSky track — bbox-filtered
            if icao in opensky_active:
                track_data = collector.get_aircraft_track(icao)
                if track_data and 'path' in track_data:
                    new_points = [p for p in track_data['path'] if p[0] > last_ts]
                    if new_points:
                        bulk_insert_telemetry(session, icao, new_points)
                        logger.info(f"[{icao}] OpenSky: inserted {len(new_points)} points.")
                        last_ts = max(p[0] for p in new_points)
                    else:
                        logger.debug(f"[{icao}] OpenSky: up-to-date.")
                else:
                    logger.debug(f"[{icao}] OpenSky: no live data.")

            # FR24 track — no bbox restriction; DB PK rejects duplicates
            if fr24 and icao in fr24_active:
                fr24_id = fr24_cache[icao].get('fr24_id')
                if fr24_id:
                    fr24_points = fr24.get_track(icao, fr24_id)
                    if fr24_points:
                        bulk_insert_telemetry(session, icao, fr24_points, source='fr24')
                        logger.info(f"[{icao}] FR24: submitted {len(fr24_points)} points.")
                else:
                    logger.debug(f"[{icao}] FR24: no flight ID, skipping track.")

            # ADSB cache — insert all cached points; DB PK (icao24, timestamp) rejects duplicates.
            # Group by source so each bulk call gets a uniform source tag.
            if icao in adsb_cache:
                by_source = {}
                for ts_str, point in adsb_cache[icao].items():
                    src = point['source']
                    row = [
                        int(ts_str),
                        point['lat'],
                        point['lon'],
                        round(point['baro_alt'] / 3.28084, 1) if point['baro_alt'] not in (None, 'ground') else None,
                        point['true_track'],
                        point['on_ground'],
                    ]
                    by_source.setdefault(src, []).append(row)
                total = 0
                for src, rows in by_source.items():
                    bulk_insert_telemetry(session, icao, rows, source=src)
                    total += len(rows)
                if total:
                    logger.info(f"[{icao}] ADSB cache: submitted {total} points ({list(by_source.keys())}).")

            time.sleep(0.5)

        # Clear the cache after successful merge
        if os.path.exists(ADSB_CACHE_FILE):
            os.remove(ADSB_CACHE_FILE)
            logger.info("ADSB cache cleared after merge.")

        logger.info("[DONE] Fleet sync completed successfully.")
        adsb_inserted = {icao for icao in full_db_icao_list if icao in adsb_cache}
        return list(set(opensky_active) | fr24_active | adsb_inserted)


    except Exception as e:
        logger.critical(f"Orchestrator failed: {e}")
        raise
    finally:
        if session:
            session.close()
            logger.info("Database session closed.")


def discover_new_aircraft():
    """
    Scan for firefighting aircraft not yet in the DB using free ADSB sources.
    Returns list of newly discovered aircraft dicts.
    """
    SCAN_TYPE_CODES = [ 'CL2P', 'CL2T', 'AT8T', 'A139', 'EC45', 'S64', 'B214' ]
    SCAN_KEYWORDS = [
        'canadair', 'bombardier 415', 'superscooper', 'air tractor',
        'dhc-515', 'cl-215', 'cl-415', 'Leonardo AW139', 'Airbus Helicopters H145',
        'Airbus Helicopters H125', 'Erickson S-64F Skycrane', 'BELL 214'
    ]
    SCAN_RADIUS_NM  = 250

    SCAN_POINTS = [
        (44.6993552, 3.8424499),  # south France
        (43.5,       12.0),       # Italy
        (40.0,       -2.0),       # Spain
        (39.3,       22.7),       # Greece
        (38.3,       29.8),       # Turkey
    ]

    blacklist = get_cached_icao_list() or []
    logger.info(f"Blacklist loaded: {len(blacklist)} known aircraft")

    sources = [
        AdsbV2Collector('adsbfi'),
        AdsbV2Collector('adsbonelol'),
        AdsbV2Collector('adsboneapi'),
    ]

    seen = set()
    findings = []

    for lat, lon in SCAN_POINTS:
        with ThreadPoolExecutor() as ex:
            all_results = list(ex.map(
                lambda s: s.scan_by_area(
                    lat=lat, lon=lon,
                    radius_nm=SCAN_RADIUS_NM,
                    model_keywords=SCAN_KEYWORDS,
                    type_codes=SCAN_TYPE_CODES,
                    blacklist=blacklist
                ),
                sources
            ))
        for source_results in all_results:
            for ac in source_results:
                if ac['icao24'] and ac['icao24'] not in seen:
                    seen.add(ac['icao24'])
                    findings.append(ac)
        time.sleep(1)  # respect 1 req/sec rate limit between scan points

    logger.info(f"Discovery complete: {len(findings)} new aircraft found across {len(sources)} sources and {len(SCAN_POINTS)} scan points.")
    return findings

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

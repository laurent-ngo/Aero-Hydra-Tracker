import os
import csv
import json
import math
import time
import random
import logging
import requests
from datetime import datetime, timedelta
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

from migrate import SessionLocal, FirmsFireIncident, FirmsHotspot

logger = logging.getLogger(__name__)

FIRMS_API_KEY  = os.getenv('NASA_API_KEY')
FIRMS_BASE_URL = 'https://firms.modaps.eosdis.nasa.gov/api/area/csv'

# France + Italy bounding box (west,south,east,north). Add more entries to expand.
SCAN_REGIONS = [
    {'name': 'france_italy', 'bbox': '-5,36,19,51'},
]

FIRMS_SOURCES_NRT = ['VIIRS_NOAA20_NRT', 'VIIRS_SNPP_NRT']
FIRMS_SOURCES_SP  = ['VIIRS_NOAA20_SP',  'VIIRS_SNPP_SP']   # standard/archive (>7 days old)
NRT_CUTOFF_DAYS   = 7    # NRT date param is only reliable for the last 7 days

FIRE_BUFFER_KM   = 1.0   # km buffer around union of hotspot geometries
FIRE_CLOSE_DAYS  = 3     # close fire if no hotspot detected for this many days
COMMIT_BATCH     = 200   # flush to disk every N hotspots
FIRE_MATCH_DEG   = 2.0   # ~220 km bbox pre-filter before shapely intersects()
DEADLOCK_RETRIES = 4     # max retries on concurrent deadlock


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _hotspot_geom(lat, lon, scan_km, track_km):
    """Pixel footprint: ellipse approximated as circle with mean radius."""
    radius_deg = ((scan_km + track_km) / 2) / 2 / 111.32
    return Point(lon, lat).buffer(radius_deg)

def _fire_perimeter(geoms, buffer_km, centroid_lat):
    union = unary_union(geoms)
    cos_lat = math.cos(math.radians(centroid_lat))
    buf_deg = buffer_km / (111.32 * cos_lat)
    return union.buffer(buf_deg)

def _area_ha(polygon):
    centroid = polygon.centroid
    cos_lat  = math.cos(math.radians(centroid.y))
    km2      = polygon.area * (111.32 ** 2) * cos_lat
    return round(km2 * 100, 1)


# ── FIRMS fetch ───────────────────────────────────────────────────────────────

def fetch_firms_csv(bbox, source, date_str, day_range=1):
    url = f"{FIRMS_BASE_URL}/{FIRMS_API_KEY}/{source}/{bbox}/{day_range}/{date_str}"
    logger.debug(f"FIRMS fetch: {url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    lines = resp.text.strip().splitlines()
    if len(lines) < 2:
        return []
    return list(csv.DictReader(lines))


# ── Fire linking ──────────────────────────────────────────────────────────────

def _source_id(row):
    return f"{row['acq_date']}_{row.get('acq_time','')}_{float(row['latitude']):.4f}_{float(row['longitude']):.4f}_{row.get('satellite','')}"

def _matching_fires(session, hotspot_geom, acq_date):
    from datetime import date as _date, timedelta as _td
    d = _date.fromisoformat(acq_date)
    date_min = (d - _td(days=2)).isoformat()
    date_max = (d + _td(days=2)).isoformat()
    centroid = hotspot_geom.centroid
    fires = session.query(FirmsFireIncident).filter(
        FirmsFireIncident.status == 'active',
        FirmsFireIncident.last_detected  >= date_min,
        FirmsFireIncident.first_detected <= date_max,
        FirmsFireIncident.centroid_lat.between(centroid.y - FIRE_MATCH_DEG, centroid.y + FIRE_MATCH_DEG),
        FirmsFireIncident.centroid_lon.between(centroid.x - FIRE_MATCH_DEG, centroid.x + FIRE_MATCH_DEG),
    ).all()
    return [f for f in fires if f.perimeter and shape(json.loads(f.perimeter)).intersects(hotspot_geom)]

def _merge_fires(session, fires):
    """Keep oldest fire, close the rest and reassign their hotspots."""
    primary = min(fires, key=lambda f: f.first_detected)
    for other in fires:
        if other.id == primary.id:
            continue
        session.query(FirmsHotspot).filter(
            FirmsHotspot.fire_id == other.id
        ).update({'fire_id': primary.id})
        other.status = 'closed'
        logger.info(f"FIRMS: merged fire {other.id} → {primary.id}")
    return primary

def _recompute_perimeter(session, fire):
    hotspots = session.query(FirmsHotspot).filter(FirmsHotspot.fire_id == fire.id).all()
    if not hotspots:
        return
    geoms = [shape(json.loads(h.geometry)) for h in hotspots if h.geometry]
    if not geoms:
        return
    centroid_lat = sum(h.lat for h in hotspots) / len(hotspots)
    perimeter = _fire_perimeter(geoms, fire.buffer_km, centroid_lat)
    centroid   = perimeter.centroid
    fire.perimeter     = json.dumps(mapping(perimeter))
    fire.centroid_lat  = round(centroid.y, 5)
    fire.centroid_lon  = round(centroid.x, 5)
    fire.area_ha       = _area_ha(perimeter)
    fire.hotspot_count = len(hotspots)
    fire.max_frp       = max((h.frp or 0) for h in hotspots)

def process_hotspot(session, row):
    src_id = _source_id(row)

    lat      = float(row['latitude'])
    lon      = float(row['longitude'])
    scan_km  = float(row.get('scan',  0.5))
    track_km = float(row.get('track', 0.5))
    geom     = _hotspot_geom(lat, lon, scan_km, track_km)
    geom_str = json.dumps(mapping(geom))

    existing = session.query(FirmsHotspot).filter(FirmsHotspot.source_id == src_id).first()
    if existing:
        if existing.geometry == geom_str:
            return 'skipped'  # identical — nothing to do
        # geometry changed (recalibrated scan/track) — update in place
        existing.lat      = lat
        existing.lon      = lon
        existing.scan_km  = scan_km
        existing.track_km = track_km
        existing.geometry = geom_str
        frp = None
        try:
            frp = float(row['frp']) if row.get('frp') else None
        except ValueError:
            pass
        existing.frp        = frp
        existing.fetched_at = int(time.time())
        session.flush()
        _recompute_perimeter(session, session.query(FirmsFireIncident).get(existing.fire_id))
        session.flush()
        logger.info(f"FIRMS: updated hotspot {src_id} (geometry changed)")
        return 'updated'

    matches = _matching_fires(session, geom, row['acq_date'])

    if len(matches) > 1:
        fire = _merge_fires(session, matches)
    elif len(matches) == 1:
        fire = matches[0]
    else:
        fire = FirmsFireIncident(
            first_detected=row['acq_date'],
            last_detected =row['acq_date'],
            status        ='active',
            buffer_km     =FIRE_BUFFER_KM,
        )
        session.add(fire)
        session.flush()
        logger.info(f"FIRMS: new fire {fire.id} at {lat:.4f},{lon:.4f}")

    frp = None
    try:
        frp = float(row['frp']) if row.get('frp') else None
    except ValueError:
        pass

    hotspot = FirmsHotspot(
        source_id  = src_id,
        fire_id    = fire.id,
        acq_date   = row['acq_date'],
        acq_time   = row.get('acq_time', ''),
        lat        = lat,
        lon        = lon,
        scan_km    = scan_km,
        track_km   = track_km,
        confidence = str(row.get('confidence', '')),
        frp        = frp,
        satellite  = row.get('satellite', ''),
        instrument = row.get('instrument', ''),
        geometry   = json.dumps(mapping(geom)),
        fetched_at = int(time.time()),
    )
    session.add(hotspot)
    session.flush()

    fire.last_detected  = max(fire.last_detected,  row['acq_date'])
    fire.first_detected = min(fire.first_detected, row['acq_date'])
    _recompute_perimeter(session, fire)
    session.flush()


# ── Stale fire closure ────────────────────────────────────────────────────────

def close_stale_fires(session):
    # Advisory lock ensures only one concurrent process runs this
    got_lock = session.execute(text("SELECT pg_try_advisory_lock(20260811)")).scalar()
    if not got_lock:
        logger.info("FIRMS: close_stale_fires skipped (another process holds the lock)")
        return
    try:
        cutoff = (datetime.utcnow() - timedelta(days=FIRE_CLOSE_DAYS)).strftime('%Y-%m-%d')
        n = session.query(FirmsFireIncident).filter(
            FirmsFireIncident.status == 'active',
            FirmsFireIncident.last_detected < cutoff,
        ).update({'status': 'closed'}, synchronize_session=False)
        session.commit()
        if n:
            logger.info(f"FIRMS: closed {n} stale fires (last_detected < {cutoff})")
    except OperationalError as e:
        session.rollback()
        logger.warning(f"FIRMS: close_stale_fires failed ({e})")
    finally:
        session.execute(text("SELECT pg_advisory_unlock(20260811)"))
        session.commit()


# ── Duplicate fire merge ──────────────────────────────────────────────────────

MERGE_MATCH_DEG = 0.3   # ~33 km centroid bbox for duplicate merge (fires are small)

def merge_duplicate_fires(session):
    """Merge fires that directly overlap in both time and geometry.
    No transitivity: A merges into B only if their perimeters physically intersect.
    """
    fires = session.query(FirmsFireIncident).filter(
        FirmsFireIncident.perimeter.isnot(None),
        FirmsFireIncident.centroid_lat.isnot(None),
    ).order_by(FirmsFireIncident.first_detected).all()

    logger.info(f"FIRMS merge: scanning {len(fires)} fires for duplicates")

    absorbed = set()   # ids already merged into another fire
    merged   = 0

    for i, fa in enumerate(fires):
        if fa.id in absorbed:
            continue
        geom_a    = None
        did_merge = False

        for fb in fires[i + 1:]:
            if fb.id in absorbed:
                continue
            # Date ranges must actually overlap
            if fa.last_detected < fb.first_detected or fb.last_detected < fa.first_detected:
                continue
            # Centroid must be close (fires are small — 0.3° ≈ 33 km)
            if abs(fa.centroid_lat - fb.centroid_lat) > MERGE_MATCH_DEG:
                continue
            if abs(fa.centroid_lon - fb.centroid_lon) > MERGE_MATCH_DEG:
                continue
            # Shapely intersection — only runs for nearby, date-overlapping candidates
            if geom_a is None:
                geom_a = shape(json.loads(fa.perimeter))
            if not geom_a.intersects(shape(json.loads(fb.perimeter))):
                continue

            # Merge fb → fa (fa is older, sorted by first_detected)
            n = session.query(FirmsHotspot).filter(
                FirmsHotspot.fire_id == fb.id
            ).update({'fire_id': fa.id}, synchronize_session=False)
            fb.status = 'closed'
            absorbed.add(fb.id)
            did_merge = True
            merged += 1
            logger.info(f"FIRMS merge: fire {fb.id} ({fb.first_detected}→{fb.last_detected}) → {fa.id} ({n} hotspots)")

        if did_merge:
            _recompute_perimeter(session, fa)
            session.flush()
            if merged % 50 == 0:
                session.commit()

    if merged:
        session.commit()
        logger.info(f"FIRMS merge: done — {merged} duplicate fires merged")
    else:
        logger.info("FIRMS merge: no duplicates found")


# ── CSV file import ───────────────────────────────────────────────────────────

def import_firms_csv_files(paths):
    """Import FIRMS CSV files downloaded from the portal into the database."""
    session = SessionLocal()
    try:
        for path in paths:
            logger.info(f"FIRMS import: reading {path}")
            with open(path, newline='', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
            logger.info(f"FIRMS import: {len(rows)} rows in {path}")
            ok = skipped = updated = errors = pending = 0
            for row in rows:
                for attempt in range(DEADLOCK_RETRIES):
                    try:
                        result = process_hotspot(session, row)
                        if result == 'updated':
                            updated += 1
                        elif result == 'skipped':
                            skipped += 1
                        else:
                            ok += 1
                        pending += 1
                        if pending >= COMMIT_BATCH:
                            session.commit()
                            pending = 0
                        break
                    except OperationalError as e:
                        session.rollback()
                        pending = 0
                        if 'deadlock' in str(e).lower() and attempt < DEADLOCK_RETRIES - 1:
                            time.sleep(random.uniform(0.1, 0.5) * (attempt + 1))
                            continue
                        logger.warning(f"FIRMS import: hotspot error ({e})")
                        errors += 1
                        break
                    except Exception as e:
                        logger.warning(f"FIRMS import: hotspot error ({e})")
                        session.rollback()
                        pending = 0
                        errors += 1
                        break
            if pending:
                session.commit()
            logger.info(f"FIRMS import: {path} — {ok} new, {updated} updated, {skipped} skipped, {errors} errors")
        try:
            close_stale_fires(session)
        except Exception as e:
            logger.warning(f"FIRMS import: close_stale_fires skipped ({e})")
        logger.info("FIRMS import: complete.")
    finally:
        session.close()


# ── Public entry point ────────────────────────────────────────────────────────

def _iter_days(date_start_str, date_end_str):
    """Yield each date between start and end inclusive as YYYY-MM-DD."""
    from datetime import date as _date, timedelta as _td
    cur = _date.fromisoformat(date_start_str)
    end = _date.fromisoformat(date_end_str)
    while cur <= end:
        yield cur.isoformat()
        cur += _td(days=1)

def run_firms_sync(days=5, date_start=None, date_end=None):
    """
    date_start / date_end: YYYY-MM-DD strings (optional).
    When provided they override `days`.
    - Recent dates (≤ NRT_CUTOFF_DAYS): NRT sources, up to 10 days per request.
    - Older dates: SP (archive) sources, one day per request (API constraint).
    """
    if not FIRMS_API_KEY:
        logger.error("NASA_API_KEY not set — skipping FIRMS sync.")
        return

    from datetime import date as _date, timedelta as _td
    today = _date.today()

    end   = _date.fromisoformat(date_end)   if date_end   else today
    start = _date.fromisoformat(date_start) if date_start else end - _td(days=days - 1)

    # Split the full range into an SP portion (old) and an NRT portion (recent)
    nrt_boundary = today - _td(days=NRT_CUTOFF_DAYS)
    sp_end   = min(end,   nrt_boundary - _td(days=1))
    nrt_start = max(start, nrt_boundary)

    session = SessionLocal()
    try:
        pending = 0

        def _process_row(row):
            nonlocal pending
            try:
                process_hotspot(session, row)
                pending += 1
                if pending >= COMMIT_BATCH:
                    session.commit()
                    pending = 0
            except Exception as e:
                logger.warning(f"FIRMS: hotspot error ({e})")
                session.rollback()
                pending = 0

        # ── SP (archive): one day at a time ──────────────────────────────────
        if start <= sp_end:
            for day in _iter_days(start.isoformat(), sp_end.isoformat()):
                for region in SCAN_REGIONS:
                    for source in FIRMS_SOURCES_SP:
                        logger.info(f"FIRMS: fetching {source} / {region['name']} / 1d on {day}")
                        try:
                            rows = fetch_firms_csv(region['bbox'], source, day, day_range=1)
                            logger.info(f"FIRMS: {len(rows)} hotspots from {source} on {day}")
                            for row in rows:
                                _process_row(row)
                        except Exception as e:
                            logger.error(f"FIRMS: fetch error for {source} on {day}: {e}")
                        time.sleep(0.5)

        # ── NRT: one day at a time (API rejects day_range > 1) ───────────────
        if nrt_start <= end:
            for day in _iter_days(nrt_start.isoformat(), end.isoformat()):
                for region in SCAN_REGIONS:
                    for source in FIRMS_SOURCES_NRT:
                        logger.info(f"FIRMS: fetching {source} / {region['name']} / 1d on {day}")
                        try:
                            rows = fetch_firms_csv(region['bbox'], source, day, day_range=1)
                            logger.info(f"FIRMS: {len(rows)} hotspots from {source} on {day}")
                            for row in rows:
                                _process_row(row)
                        except Exception as e:
                            logger.error(f"FIRMS: fetch error for {source} on {day}: {e}")
                        time.sleep(0.5)

        if pending:
            session.commit()
        close_stale_fires(session)
        logger.info("FIRMS: sync complete.")
    finally:
        session.close()

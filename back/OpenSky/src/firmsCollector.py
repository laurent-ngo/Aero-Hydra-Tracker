import os
import csv
import json
import math
import time
import logging
import requests
from datetime import datetime, timedelta
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union

from migrate import SessionLocal, FirmsFireIncident, FirmsHotspot

logger = logging.getLogger(__name__)

FIRMS_API_KEY  = os.getenv('NASA_API_KEY')
FIRMS_BASE_URL = 'https://firms.modaps.eosdis.nasa.gov/api/area/csv'

# France + Italy bounding box (west,south,east,north). Add more entries to expand.
SCAN_REGIONS = [
    {'name': 'france_italy', 'bbox': '-5,36,19,51'},
]

FIRMS_SOURCES    = ['VIIRS_NOAA20_NRT', 'VIIRS_SNPP_NRT']
FIRE_BUFFER_KM   = 1.0   # km buffer around union of hotspot geometries
FIRE_CLOSE_DAYS  = 3     # close fire if no hotspot detected for this many days


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

def _matching_fires(session, hotspot_geom):
    fires = session.query(FirmsFireIncident).filter(
        FirmsFireIncident.status == 'active'
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
    if session.query(FirmsHotspot).filter(FirmsHotspot.source_id == src_id).first():
        return  # already stored

    lat      = float(row['latitude'])
    lon      = float(row['longitude'])
    scan_km  = float(row.get('scan',  0.5))
    track_km = float(row.get('track', 0.5))
    geom     = _hotspot_geom(lat, lon, scan_km, track_km)

    matches = _matching_fires(session, geom)

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

    fire.last_detected = max(fire.last_detected, row['acq_date'])
    _recompute_perimeter(session, fire)
    session.commit()


# ── Stale fire closure ────────────────────────────────────────────────────────

def close_stale_fires(session):
    cutoff = (datetime.utcnow() - timedelta(days=FIRE_CLOSE_DAYS)).strftime('%Y-%m-%d')
    stale = session.query(FirmsFireIncident).filter(
        FirmsFireIncident.status == 'active',
        FirmsFireIncident.last_detected < cutoff,
    ).all()
    for fire in stale:
        fire.status = 'closed'
        logger.info(f"FIRMS: closed stale fire {fire.id} (last seen {fire.last_detected})")
    if stale:
        session.commit()


# ── Public entry point ────────────────────────────────────────────────────────

def run_firms_sync(days=5):
    if not FIRMS_API_KEY:
        logger.error("NASA_API_KEY not set — skipping FIRMS sync.")
        return

    session = SessionLocal()
    try:
        today = datetime.utcnow().strftime('%Y-%m-%d')
        for region in SCAN_REGIONS:
            for source in FIRMS_SOURCES:
                logger.info(f"FIRMS: fetching {source} / {region['name']} / last {days}d")
                try:
                    rows = fetch_firms_csv(region['bbox'], source, today, day_range=min(days, 5))
                    logger.info(f"FIRMS: {len(rows)} hotspots from {source}")
                    for row in rows:
                        try:
                            process_hotspot(session, row)
                        except Exception as e:
                            logger.warning(f"FIRMS: hotspot error ({e})")
                            session.rollback()
                except Exception as e:
                    logger.error(f"FIRMS: fetch error for {source}: {e}")
                time.sleep(1)
        close_stale_fires(session)
        logger.info("FIRMS: sync complete.")
    finally:
        session.close()

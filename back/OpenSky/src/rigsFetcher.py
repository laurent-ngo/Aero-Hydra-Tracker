"""
Fetches oil/gas facility locations from:
  - EMODNET Human Activities WFS  (European offshore platforms)
  - OSM Overpass API               (onshore Europe + North America: refineries,
                                    processing plants, LNG, offshore platforms)

Individual wellheads are excluded — too numerous (100k+ in North America alone)
and not useful for fire classification.
"""
import time
import math
import logging
import requests

from sqlalchemy.dialects.postgresql import insert as pg_insert
from migrate import SessionLocal, OilGasFacility

logger = logging.getLogger(__name__)

RIG_PROXIMITY_KM = 2.0   # fires within this distance of a facility → 'industrial'

# OSM tags for significant oil/gas infrastructure only.
# Individual wells (~100k+ in North America) and fuel stations are intentionally excluded.
OSM_QUERY_TEMPLATE = """
[out:json][timeout:120];
(
  node["man_made"="offshore_platform"]({bbox});
  node["industrial"="refinery"]({bbox});
  way["industrial"="refinery"]({bbox});
  node["industrial"="oil_refinery"]({bbox});
  way["industrial"="oil_refinery"]({bbox});
  node["man_made"="works"]["product"="refinery"]({bbox});
  way["man_made"="works"]["product"="refinery"]({bbox});
  node["man_made"="works"]["product"="oil"]({bbox});
  node["man_made"="works"]["product"="gas"]({bbox});
  node["industrial"="gas"]({bbox});
  node["industrial"="lng_terminal"]({bbox});
  node["man_made"="lng_terminal"]({bbox});
  way["man_made"="lng_terminal"]({bbox});
);
out center tags;
"""

OSM_REGIONS = [
    # Europe split into quadrants to stay under Overpass timeout
    ('EU_NW', '47,-25,72,15'),
    ('EU_NE', '47,15,72,45'),
    ('EU_SW', '34,-25,47,15'),
    ('EU_SE', '34,15,47,45'),
    # Continental US
    ('US_W', '24,-125,50,-95'),
    ('US_E', '24,-95,50,-65'),
    # Alaska
    ('AK', '54,-170,72,-130'),
    # Canada
    ('CA_W', '48,-140,70,-96'),
    ('CA_E', '42,-96,70,-52'),
]

# Fix: Overpass wants south,west,north,east — reorder from our west,south,east,north format
def _bbox_for_overpass(region_bbox_str):
    """Convert 'south,west,north,east' string to Overpass bbox format (same order)."""
    return region_bbox_str


def _osm_facility_type(tags):
    t = tags.get
    industrial = t('industrial', '')
    man_made   = t('man_made', '')
    product    = t('product', '')

    if 'refinery' in industrial or 'refinery' in man_made or product == 'refinery':
        return 'refinery'
    if industrial == 'lng_terminal' or man_made == 'lng_terminal':
        return 'lng'
    if industrial == 'gas' or product == 'gas':
        return 'gas_plant'
    if man_made == 'offshore_platform':
        return 'platform'
    if man_made == 'petroleum_well':
        return 'well'
    if 'storage_tank' in man_made and t('content', '') in ('oil', 'gas'):
        return 'storage'
    return 'other'


def fetch_emodnet(session):
    """European offshore platforms from EMODNET Human Activities."""
    url = (
        'https://ows.emodnet-humanactivities.eu/geoserver/emodnet/ows'
        '?service=WFS&version=1.1.0&request=GetFeature'
        '&typeName=emodnet:platforms&outputFormat=application/json'
    )
    logger.info('RIGS: fetching EMODNET platforms …')
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f'RIGS: EMODNET fetch failed: {e}')
        return 0

    rows = []
    for feat in data.get('features', []):
        props = feat.get('properties', {})
        geom  = feat.get('geometry', {})
        if geom.get('type') != 'Point':
            continue
        lon, lat = geom['coordinates'][:2]
        source_id = 'emodnet:' + str(props.get('id') or props.get('gml_id') or f'{lat:.5f},{lon:.5f}')
        status_raw = str(props.get('status', '') or '').lower()
        status = 'inactive' if any(w in status_raw for w in ('decommission', 'abandon', 'removed')) else 'active'
        rows.append({
            'source':        'emodnet',
            'source_id':     source_id,
            'name':          props.get('name') or props.get('platform_name'),
            'operator':      props.get('operator') or props.get('company'),
            'lat':           round(lat, 6),
            'lon':           round(lon, 6),
            'facility_type': 'platform',
            'country':       props.get('country') or props.get('country_code'),
            'status':        status,
            'imported_at':   int(time.time()),
        })

    if rows:
        stmt = pg_insert(OilGasFacility).values(rows).on_conflict_do_nothing(index_elements=['source_id'])
        result = session.execute(stmt)
        session.commit()
        added = result.rowcount if result.rowcount >= 0 else len(rows)
    else:
        added = 0

    logger.info(f'RIGS: EMODNET done — {added} inserted (duplicates skipped)')
    return added


def fetch_osm_region(session, region_name, bbox_str):
    """Fetch OSM oil/gas facilities for one bounding box (south,west,north,east)."""
    query = OSM_QUERY_TEMPLATE.replace('{bbox}', bbox_str)
    url = 'https://overpass-api.de/api/interpreter'
    headers = {'User-Agent': 'aero-hydra-tracker/1.0 (fire-monitoring; contact: laurent.nnd@googlemail.com)'}
    logger.info(f'RIGS: OSM {region_name} ({bbox_str}) …')
    for attempt in range(3):
        try:
            r = requests.post(url, data={'data': query}, headers=headers, timeout=180)
            if r.status_code == 429:
                wait = 60 * (attempt + 1)
                logger.warning(f'RIGS: OSM {region_name} rate-limited, retrying in {wait}s …')
                time.sleep(wait)
                continue
            if not r.ok:
                logger.error(f'RIGS: OSM {region_name} failed: {r.status_code} — {r.text[:300]}')
                return 0
            elements = r.json().get('elements', [])
            break
        except Exception as e:
            logger.error(f'RIGS: OSM {region_name} failed: {e}')
            return 0
    else:
        logger.error(f'RIGS: OSM {region_name} gave up after 3 attempts')
        return 0

    rows = []
    for el in elements:
        if el['type'] == 'way' or el['type'] == 'relation':
            center = el.get('center', {})
            lat, lon = center.get('lat'), center.get('lon')
        else:
            lat, lon = el.get('lat'), el.get('lon')
        if lat is None or lon is None:
            continue

        tags = el.get('tags', {})
        rows.append({
            'source':        'osm',
            'source_id':     f'osm:{el["type"]}:{el["id"]}',
            'name':          tags.get('name') or tags.get('operator') or tags.get('ref'),
            'operator':      tags.get('operator'),
            'lat':           round(lat, 6),
            'lon':           round(lon, 6),
            'facility_type': _osm_facility_type(tags),
            'country':       tags.get('addr:country'),
            'status':        'active',
            'imported_at':   int(time.time()),
        })

    if rows:
        stmt = pg_insert(OilGasFacility).values(rows).on_conflict_do_nothing(index_elements=['source_id'])
        result = session.execute(stmt)
        session.commit()
        added = result.rowcount if result.rowcount >= 0 else len(rows)
    else:
        added = 0

    logger.info(f'RIGS: OSM {region_name} done — {added} inserted (duplicates skipped)')
    time.sleep(2)   # be polite to Overpass
    return added


def import_all_facilities():
    """Main entry point: fetch EMODNET + all OSM regions."""
    session = SessionLocal()
    try:
        total = 0
        total += fetch_emodnet(session)
        for name, bbox in OSM_REGIONS:
            # Convert our (south,west,north,east) format to Overpass (same)
            total += fetch_osm_region(session, name, bbox)
        logger.info(f'RIGS: import complete — {total} facilities total')
    finally:
        session.close()


# ── Fire classification ───────────────────────────────────────────────────────

def _dist_km(lat1, lon1, lat2, lon2):
    """Haversine distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def classify_fire(session, fire):
    """
    Check if fire centroid is within RIG_PROXIMITY_KM of any oil/gas facility.
    Updates fire.fire_type, fire.nearest_facility_id, fire.nearest_facility_km in place.
    Caller must commit.
    """
    if fire.centroid_lat is None or fire.centroid_lon is None:
        return

    # Degree bbox pre-filter: 2 km ≈ 0.018°
    pad = RIG_PROXIMITY_KM / 111.0
    candidates = session.query(OilGasFacility).filter(
        OilGasFacility.status == 'active',
        OilGasFacility.lat.between(fire.centroid_lat - pad, fire.centroid_lat + pad),
        OilGasFacility.lon.between(fire.centroid_lon - pad, fire.centroid_lon + pad),
    ).all()

    if not candidates:
        fire.fire_type           = 'natural'
        fire.nearest_facility_id = None
        fire.nearest_facility_km = None
        return

    nearest = min(candidates, key=lambda f: _dist_km(fire.centroid_lat, fire.centroid_lon, f.lat, f.lon))
    dist = _dist_km(fire.centroid_lat, fire.centroid_lon, nearest.lat, nearest.lon)

    if dist <= RIG_PROXIMITY_KM:
        fire.fire_type           = 'industrial'
        fire.nearest_facility_id = nearest.id
        fire.nearest_facility_km = round(dist, 2)
    else:
        fire.fire_type           = 'natural'
        fire.nearest_facility_id = None
        fire.nearest_facility_km = None


def classify_all_fires():
    """Reclassify every fire in the DB — run after importing facilities."""
    from migrate import FirmsFireIncident
    session = SessionLocal()
    try:
        fires = session.query(FirmsFireIncident).filter(
            FirmsFireIncident.centroid_lat.isnot(None)
        ).all()
        logger.info(f'RIGS: classifying {len(fires)} fires …')
        for i, fire in enumerate(fires):
            classify_fire(session, fire)
            if (i + 1) % 500 == 0:
                session.commit()
                logger.info(f'RIGS: classified {i+1}/{len(fires)}')
        session.commit()
        industrial = sum(1 for f in fires if f.fire_type == 'industrial')
        logger.info(f'RIGS: done — {industrial} industrial, {len(fires)-industrial} natural')
    finally:
        session.close()

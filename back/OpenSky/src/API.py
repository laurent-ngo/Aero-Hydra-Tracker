from fastapi import FastAPI, Depends, HTTPException, Query, Security, status
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import pathlib

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import List, Optional
from typing_extensions import Annotated

import migrate
from migrate import FirmsFireIncident, FirmsHotspot

import time, os, json
import glob
import re
import logging
from datetime import datetime, timedelta
import numpy as np
from sklearn.cluster import DBSCAN
logger = logging.getLogger(__name__)

API_KEY = os.getenv("AERO_API_KEY")
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

app = FastAPI(title="Aero-Hydra API")

def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate credentials"
    )


# Allow your local frontend to talk to the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get the DB session per request
def get_db():
    db = migrate.SessionLocal()
    try:
        yield db
    finally:
        db.close()

DbSession = Annotated[Session, Depends(get_db)]

FRONT_DIR = (pathlib.Path(__file__).parent / ".." / ".." / ".." / "front").resolve()

@app.get("/", include_in_schema=False)
def serve_root():
    return RedirectResponse(url="/skywatch.html", status_code=302)


def _get_aircraft_with_details(db: Session, icao_filter=None, bbox=None):
    """Common logic for querying aircraft, their last telemetry, and airfield names.

    bbox: optional (lat_min, lat_max, lon_min, lon_max) tuple — when given, restricts
    results to aircraft whose last known position falls within it (saves payload size
    for viewport-based frontend requests).
    """
    query = db.query(
        migrate.TrackedAircraft,
        migrate.Airfield,
        migrate.FlightTelemetry,
        migrate.WaterLocation
    ).filter(
        migrate.TrackedAircraft.visible == True
    ).outerjoin(
        migrate.FlightTelemetry,
        and_(
            migrate.TrackedAircraft.icao24 == migrate.FlightTelemetry.icao24,
            migrate.TrackedAircraft.last_seen == migrate.FlightTelemetry.timestamp
        )
    ).outerjoin(
        migrate.Airfield,
        migrate.FlightTelemetry.latest_airfield == migrate.Airfield.icao
    ).outerjoin(
        migrate.WaterLocation,
        migrate.FlightTelemetry.latest_waterfield == migrate.WaterLocation.ref
    )

    if icao_filter is not None:
        query = query.filter(migrate.TrackedAircraft.icao24.in_(icao_filter))

    if bbox is not None:
        lat_min, lat_max, lon_min, lon_max = bbox
        query = query.filter(
            migrate.FlightTelemetry.lat.between(lat_min, lat_max),
            migrate.FlightTelemetry.lon.between(lon_min, lon_max),
        )

    results = query.all()

    return [
        {
            "icao24": a.icao24, 
            "registration": a.registration, 
            "country": a.country,
            "owner": a.owner,
            "payload_capacity_kg": a.payload_capacity_kg,
            "model": a.aircraft_model,
            "type": a.aircraft_type,
            "sea_landing": a.sea_landing,
            "icon": a.icon_id, 
            "icon_size": a.icon_size,
            "is_full": ft.is_full if ft else None,
            "at_airfield": ft.at_airfield if ft else None,
           
            "last_timestamp": a.last_seen,
            "true_track": ft.true_track if ft else None,
            "last_location": ft.location if ft else None,  # country or sea/ocean name, resolved daily

            "last_airfield": ft.latest_airfield if ft else "", # The ICAO code (e.g., LSGG)
            "airfield_name": af.name if af else "Unknown", # The full name
            "airfield_lat": af.lat if af else "Unknown", # The full name
            "airfield_lon": af.lon if af else "Unknown", # The full name
            
            "last_waterfield": ft.latest_waterfield if ft else "", # The ICAO code (e.g., RA01)
            "waterfield_name": wl.name if wl else "",
            "waterfield_lat": wl.lat if wl else None,
            "waterfield_lon": wl.lon if wl else None,

            "last_lat": ft.lat if ft else None,
            "last_lon": ft.lon if ft else None,
            "last_speed_kt": ft.speed_kt if ft else None,
            "last_speed_kph": ft.speed_kph if ft else None,
            "last_baro_alt_ft": ft.baro_altitude_ft if ft else None,
            "last_agl_alt_ft": ft.altitude_agl_ft if ft else None
        } for a, af, ft, wl in results
    ]


@app.get("/aircraft", response_model=List[dict], dependencies=[Security(get_api_key)])
def list_aircraft(db: DbSession):
    return _get_aircraft_with_details(db)


@app.get("/aircraft/active", response_model=List[dict], dependencies=[Security(get_api_key)])
def list_active_aircraft(
    start: int,
    stop: int,
    db: DbSession,
    lat_min: Optional[float] = Query(None),
    lat_max: Optional[float] = Query(None),
    lon_min: Optional[float] = Query(None),
    lon_max: Optional[float] = Query(None),
):
    # 1. Get unique ICAOs that have telemetry within the timeframe
    active_icaos = db.query(migrate.FlightTelemetry.icao24).filter(
        migrate.FlightTelemetry.timestamp >= start,
        migrate.FlightTelemetry.timestamp <= stop
    ).distinct().all()


    icao_list = [i[0] for i in active_icaos]

    # 2. Optional bbox — restrict to aircraft last seen within the viewport
    bbox = None
    if all(v is not None for v in (lat_min, lat_max, lon_min, lon_max)):
        bbox = (lat_min, lat_max, lon_min, lon_max)

    # 3. Use helper with the icao filter
    return _get_aircraft_with_details(db, icao_filter=icao_list, bbox=bbox)
    
@app.get("/telemetry/{icao24}", responses={400: {"description": "icao24 not found"}}, dependencies=[Security(get_api_key)])
def get_telemetry(
    db: DbSession,
    icao24: str,
    start: Optional[int] = None,
    stop: Optional[int] = None,
    limit: int = 10000,
    lat_min: Optional[float] = Query(None),
    lat_max: Optional[float] = Query(None),
    lon_min: Optional[float] = Query(None),
    lon_max: Optional[float] = Query(None),
):
    # Validation: 24-hour check (86400 seconds)
    if start is None and stop is None:
        stop = int(time.time())
        start = stop - 86400

    elif stop is None:
        stop = int(time.time())

    if start and stop:
        timespan = stop - start
        if timespan < 0:
            raise HTTPException(status_code=400,
                detail="Start timestamp must be before stop timestamp.")
        if timespan > 7 * 86400:
            raise HTTPException(status_code=400,
                detail="Timespan exceeds 7 days. Please reduce the range."
            )

    # Query construction
    query = db.query(migrate.FlightTelemetry).filter(
        migrate.FlightTelemetry.icao24 == icao24,
        migrate.FlightTelemetry.timestamp >= start,
        migrate.FlightTelemetry.timestamp <= stop
        )

    # Optional bbox — restrict points to the visible map area
    if all(v is not None for v in (lat_min, lat_max, lon_min, lon_max)):
        query = query.filter(
            migrate.FlightTelemetry.lat.between(lat_min, lat_max),
            migrate.FlightTelemetry.lon.between(lon_min, lon_max),
        )

    points = query.order_by(migrate.FlightTelemetry.timestamp.desc()).limit(limit).all()

    # Create a list of dictionaries with the added altitude in feet
    results = []
    for p in points:
        # Convert the SQLAlchemy model instance to a dictionary
        p_dict = {column.name: getattr(p, column.name) for column in p.__table__.columns}
        
        # Add the calculated feet (1 meter = 3.28084 feet)
        if p_dict.get("baro_altitude") is not None:
            p_dict["baro_altitude_ft"] = round(p_dict["baro_altitude"] * 3.28084)
        else:
            p_dict["baro_altitude_ft"] = None
            
        results.append(p_dict)

    return results

@app.get("/fires", dependencies=[Security(get_api_key)])
def get_fires(
    db: DbSession,
    status: Optional[str] = None,        # 'active' | 'closed'
    start:  Optional[str] = None,        # YYYY-MM-DD — fires active on or after this date
    end:    Optional[str] = None,        # YYYY-MM-DD — fires active on or before this date
    min_lat: Optional[float] = None,
    max_lat: Optional[float] = None,
    min_lon: Optional[float] = None,
    max_lon: Optional[float] = None,
    frp_categories: Optional[str] = None,  # comma-separated: low,medium,high,extreme
):
    q = db.query(FirmsFireIncident)
    if status:
        q = q.filter(FirmsFireIncident.status == status)
    if start:
        q = q.filter(FirmsFireIncident.last_detected >= start)
    if end:
        q = q.filter(FirmsFireIncident.first_detected <= end)
    if min_lat is not None:
        q = q.filter(FirmsFireIncident.centroid_lat >= min_lat)
    if max_lat is not None:
        q = q.filter(FirmsFireIncident.centroid_lat <= max_lat)
    if min_lon is not None:
        q = q.filter(FirmsFireIncident.centroid_lon >= min_lon)
    if max_lon is not None:
        q = q.filter(FirmsFireIncident.centroid_lon <= max_lon)
    if frp_categories:
        cats = {c.strip() for c in frp_categories.split(',')}
        conds = []
        if 'low'     in cats: conds.append(or_(FirmsFireIncident.max_frp == None, FirmsFireIncident.max_frp < 30))
        if 'medium'  in cats: conds.append(and_(FirmsFireIncident.max_frp >= 30,  FirmsFireIncident.max_frp < 100))
        if 'high'    in cats: conds.append(and_(FirmsFireIncident.max_frp >= 100, FirmsFireIncident.max_frp < 500))
        if 'extreme' in cats: conds.append(FirmsFireIncident.max_frp >= 500)
        if conds:
            q = q.filter(or_(*conds))
    fires = q.order_by(FirmsFireIncident.last_detected.desc()).all()
    return [
        {
            "id":             f.id,
            "status":         f.status,
            "first_detected": f.first_detected,
            "last_detected":  f.last_detected,
            "centroid_lat":   f.centroid_lat,
            "centroid_lon":   f.centroid_lon,
            "area_ha":        f.area_ha,
            "hotspot_count":  f.hotspot_count,
            "max_frp":        f.max_frp,
            "perimeter":      json.loads(f.perimeter) if f.perimeter else None,
        }
        for f in fires
    ]

@app.get("/hotspots", dependencies=[Security(get_api_key)])
def get_hotspots(
    db: DbSession,
    start:   Optional[str]   = None,
    end:     Optional[str]   = None,
    min_lat: Optional[float] = None,
    max_lat: Optional[float] = None,
    min_lon: Optional[float] = None,
    max_lon: Optional[float] = None,
    frp_categories: Optional[str] = None,
):
    q = db.query(FirmsHotspot)
    if start:   q = q.filter(FirmsHotspot.acq_date >= start)
    if end:     q = q.filter(FirmsHotspot.acq_date <= end)
    if min_lat is not None: q = q.filter(FirmsHotspot.lat >= min_lat)
    if max_lat is not None: q = q.filter(FirmsHotspot.lat <= max_lat)
    if min_lon is not None: q = q.filter(FirmsHotspot.lon >= min_lon)
    if max_lon is not None: q = q.filter(FirmsHotspot.lon <= max_lon)
    if frp_categories:
        cats = {c.strip() for c in frp_categories.split(',')}
        conds = []
        if 'low'     in cats: conds.append(or_(FirmsHotspot.frp == None, FirmsHotspot.frp < 30))
        if 'medium'  in cats: conds.append(and_(FirmsHotspot.frp >= 30,  FirmsHotspot.frp < 100))
        if 'high'    in cats: conds.append(and_(FirmsHotspot.frp >= 100, FirmsHotspot.frp < 500))
        if 'extreme' in cats: conds.append(FirmsHotspot.frp >= 500)
        if conds:
            q = q.filter(or_(*conds))
    return [{"fire_id":h.fire_id,"lat":h.lat,"lon":h.lon,"acq_date":h.acq_date,"frp":h.frp,"confidence":h.confidence,"satellite":h.satellite} for h in q.all()]


@app.get("/fires/{fire_id}/hotspots", dependencies=[Security(get_api_key)])
def get_fire_hotspots(db: DbSession, fire_id: int):
    hotspots = db.query(FirmsHotspot).filter(FirmsHotspot.fire_id == fire_id).order_by(FirmsHotspot.acq_date, FirmsHotspot.acq_time).all()
    return [
        {
            "id":         h.id,
            "acq_date":   h.acq_date,
            "acq_time":   h.acq_time,
            "lat":        h.lat,
            "lon":        h.lon,
            "confidence": h.confidence,
            "frp":        h.frp,
            "satellite":  h.satellite,
            "geometry":   json.loads(h.geometry) if h.geometry else None,
        }
        for h in hotspots
    ]

@app.get("/regions-of-interest", dependencies=[Security(get_api_key)]) # Updated to match your frontend fetch URL
def get_rois(
    db: DbSession,
    level: Annotated[Optional[int], Query(ge=1, le=4)] = None,
    type: Annotated[Optional[str], Query(pattern="^(fire|water)$", description="Filter by 'fire' or 'water'")] = None
    ):

    query = db.query(migrate.RegionOfInterest)
    
    # Filter if level is provided
    if level is not None:
        query = query.filter(migrate.RegionOfInterest.level == level)

    # Filter by Type
    if type is not None:
        query = query.filter(migrate.RegionOfInterest.type == type)
        
    rois = query.all()
    
    return [
        {
            "id": r.id,
            "name": r.name,
            "lat": r.lat,
            "lon": r.lon,
            "type": r.type,
            "level": r.level,
            "density": r.density,
            "detected_at": r.detected_at.isoformat() if r.detected_at else None,
            "geometry": r.geometry
        } for r in rois
    ]


@app.get("/active-events", dependencies=[Security(get_api_key)])
def get_active_events(
    db: DbSession,
    window_minutes: int = Query(60,  ge=5,   le=480,  description="Look-back window in minutes"),
    min_passes:     int = Query(5,   ge=2,            description="Minimum passes to form a cluster"),
    radius_km:    float = Query(2.0, ge=0.5, le=50.0, description="Cluster radius in km"),
):
    cutoff = int((datetime.now() - timedelta(minutes=window_minutes)).timestamp())

    points = db.query(migrate.FlightTelemetry).join(
        migrate.TrackedAircraft,
        migrate.FlightTelemetry.icao24 == migrate.TrackedAircraft.icao24,
    ).filter(
        migrate.FlightTelemetry.timestamp     >= cutoff,
        migrate.FlightTelemetry.on_ground     == False,
        migrate.FlightTelemetry.is_processed  == True,
        migrate.FlightTelemetry.is_over_water == False,
        migrate.FlightTelemetry.at_airfield   == False,
        migrate.FlightTelemetry.lat.isnot(None),
        migrate.FlightTelemetry.lon.isnot(None),
        migrate.TrackedAircraft.aircraft_type != 'helicopter',
    ).all()

    if len(points) < min_passes:
        return []

    coords  = np.array([[p.lat, p.lon] for p in points])
    epsilon = radius_km / 6371.0

    labels = DBSCAN(
        eps=epsilon, min_samples=min_passes,
        algorithm='ball_tree', metric='haversine'
    ).fit(np.radians(coords)).labels_

    airfields      = db.query(migrate.Airfield).filter(
        migrate.Airfield.lat.isnot(None),
        migrate.Airfield.lon.isnot(None),
    ).all()
    events = []

    for label in set(labels) - {-1}:
        mask        = labels == label
        cluster_pts = [p for p, m in zip(points, mask) if m]
        cluster_c   = coords[mask]

        centroid_lat = float(np.mean(cluster_c[:, 0]))
        centroid_lon = float(np.mean(cluster_c[:, 1]))
        aircraft     = list({p.icao24 for p in cluster_pts})

        # Nearest airfield within 10 km
        event_name = None
        best_dist = float("inf")
        for af in airfields:
            dist_km = ((af.lat - centroid_lat)**2 + (af.lon - centroid_lon)**2) ** 0.5 * 111
            if dist_km < 10 and dist_km < best_dist:
                best_dist  = dist_km
                event_name = af.name

        events.append({
            "lat":            round(centroid_lat, 5),
            "lon":            round(centroid_lon, 5),
            "pass_count":     len(cluster_pts),
            "aircraft_count": len(aircraft),
            "aircraft":       aircraft,
            "fire_location":  event_name,
            "first_pass":     min(p.timestamp for p in cluster_pts),
            "last_pass":      max(p.timestamp for p in cluster_pts),
        })

    return sorted(events, key=lambda e: e["last_pass"], reverse=True)


HEATMAP_DIR = os.getenv("HEATMAP_DIR", ".")

@app.get("/heatmaps", dependencies=[Security(get_api_key)])
def list_heatmaps():
    """Return list of available heatmap names."""
    files = glob.glob(os.path.join(HEATMAP_DIR, "heatmap_*.json"))
    names = [
        os.path.basename(f).replace("heatmap_", "").replace(".json", "")
        for f in sorted(files)
    ]
    return {"heatmaps": names}


# In-memory cache: path → (mtime, parsed_data)
_heatmap_cache: dict = {}

def _load_heatmap(path: str) -> dict:
    """Load heatmap JSON from disk, using an mtime-keyed in-memory cache."""
    mtime = os.path.getmtime(path)
    if path in _heatmap_cache and _heatmap_cache[path][0] == mtime:
        return _heatmap_cache[path][1]
    with open(path) as fh:
        data = json.load(fh)
    _heatmap_cache[path] = (mtime, data)
    return data

def _slice_heatmap(data: dict, lat_min: float, lat_max: float,
                   lon_min: float, lon_max: float) -> dict:
    """Return a sub-grid clipped to the requested bbox."""
    m          = data["metadata"]
    step_lat   = m["step_lat"]
    step_lon   = m["step_lon"]
    full_rows  = m["rows"]
    full_cols  = m["cols"]
    full_lat_min = m["lat_min"]
    full_lon_min = m["lon_min"]
    # JS convention: lat_max = lat_min + rows * step_lat (one step above actual top row)
    full_lat_max = full_lat_min + full_rows * step_lat

    # Add 2-cell padding so edge features render fully
    PAD = 2
    r0 = max(0,          int((full_lat_max - lat_max) / step_lat) - PAD)
    r1 = min(full_rows,  int((full_lat_max - lat_min) / step_lat) + PAD + 1)
    c0 = max(0,          int((lon_min - full_lon_min) / step_lon) - PAD)
    c1 = min(full_cols,  int((lon_max - full_lon_min) / step_lon) + PAD + 1)

    sub_rows = r1 - r0
    sub_cols = c1 - c0

    if sub_rows <= 0 or sub_cols <= 0:
        # bbox outside grid — return empty
        sub_rows = sub_cols = 0
        indices = []
    else:
        indices = [r * full_cols + c for r in range(r0, r1) for c in range(c0, c1)]

    def _slice_array(arr):
        return [arr[i] for i in indices] if arr else []

    values = _slice_array(data.get("values", []))
    covered = sum(1 for v in values if v is not None)

    sub_lat_min = round(full_lat_min + (full_rows - r1) * step_lat, 6)
    sub_lon_min = round(full_lon_min + c0 * step_lon, 6)

    sub_meta = dict(m)
    sub_meta.update({
        "lat_min":       sub_lat_min,
        "lat_max":       round(sub_lat_min + sub_rows * step_lat, 6),
        "lon_min":       sub_lon_min,
        "lon_max":       round(sub_lon_min + sub_cols * step_lon, 6),
        "rows":          sub_rows,
        "cols":          sub_cols,
        "total_cells":   sub_rows * sub_cols,
        "covered_cells": covered,
    })

    result = {"metadata": sub_meta, "values": values}
    # Preserve optional per-cell arrays (speed heatmap: airfields, distances, models)
    for key in ("airfields", "distances", "models"):
        if key in data:
            result[key] = _slice_array(data[key])
    return result


@app.get("/heatmap/{name}", dependencies=[Security(get_api_key)])
def get_heatmap(
    name:    str,
    lat_min: Optional[float] = Query(None),
    lat_max: Optional[float] = Query(None),
    lon_min: Optional[float] = Query(None),
    lon_max: Optional[float] = Query(None),
):
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '', name)
    path = os.path.join(HEATMAP_DIR, f"heatmap_{safe_name}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Heatmap '{safe_name}' not found")

    data = _load_heatmap(path)

    bbox_provided = all(v is not None for v in (lat_min, lat_max, lon_min, lon_max))
    if bbox_provided:
        data = _slice_heatmap(data, lat_min, lat_max, lon_min, lon_max)
        logger.info(f"Heatmap {safe_name}: bbox slice "
                    f"lat[{lat_min:.2f},{lat_max:.2f}] lon[{lon_min:.2f},{lon_max:.2f}] "
                    f"→ {data['metadata']['rows']}×{data['metadata']['cols']} cells")
    else:
        logger.info(f"Heatmap {safe_name}: full grid "
                    f"{data['metadata']['rows']}×{data['metadata']['cols']} cells")

    return data

# ── Frontend static files (mount last so API routes take priority) ──
if FRONT_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONT_DIR)), name="frontend")
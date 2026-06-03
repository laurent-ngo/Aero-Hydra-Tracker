"""
Elevation API
=============
Lightweight FastAPI service that returns ground elevation (metres + feet)
for one or many lat/lon coordinates, using the local Copernicus DEM .tif tiles.

Endpoints
---------
GET  /elevation?lat=&lon=          → single point
POST /elevation/batch              → list of {lat, lon} → list of results

Run
---
    uvicorn elevation_api:app --host 0.0.0.0 --port 8011
"""

import glob
import os
import logging
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from elevation import ElevationProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Load all .tif tiles at startup ──────────────────────────────────────────
DATA_DIR = os.getenv("ELEVATION_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))

_tif_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.tif")))
if not _tif_files:
    raise RuntimeError(f"No .tif files found in {DATA_DIR}")

providers: List[ElevationProvider] = []
for path in _tif_files:
    try:
        providers.append(ElevationProvider(path))
        logger.info(f"Loaded tile: {os.path.basename(path)}")
    except Exception as e:
        logger.warning(f"Could not load {path}: {e}")

logger.info(f"{len(providers)} elevation tile(s) ready")

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Elevation API", version="1.0")


def _query(lat: float, lon: float) -> Optional[float]:
    """Return ground elevation in metres, or None if no tile covers the point."""
    for p in providers:
        elev = p.get_elevation(lat, lon)
        if elev is not None:
            return elev
    return None


# ── Single point ─────────────────────────────────────────────────────────────
@app.get("/elevation")
def get_elevation(lat: float, lon: float):
    """
    Returns ground elevation for a single coordinate.

    Example: GET /elevation?lat=43.75&lon=4.42
    """
    elev_m = _query(lat, lon)
    if elev_m is None:
        raise HTTPException(status_code=404, detail="No elevation data for this location")
    return {
        "lat": lat,
        "lon": lon,
        "elevation_m": round(elev_m, 1),
        "elevation_ft": round(elev_m * 3.28084, 1),
    }


# ── Batch ─────────────────────────────────────────────────────────────────────
class Point(BaseModel):
    lat: float
    lon: float

@app.post("/elevation/batch")
def get_elevation_batch(points: List[Point]):
    """
    Returns ground elevation for a list of coordinates.
    Points with no coverage return null values (never raises 404).

    Example body: [{"lat": 43.75, "lon": 4.42}, {"lat": 41.9, "lon": 12.5}]
    """
    results = []
    for p in points:
        elev_m = _query(p.lat, p.lon)
        results.append({
            "lat": p.lat,
            "lon": p.lon,
            "elevation_m": round(elev_m, 1) if elev_m is not None else None,
            "elevation_ft": round(elev_m * 3.28084, 1) if elev_m is not None else None,
        })
    return results


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "tiles_loaded": len(providers)}

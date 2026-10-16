"""
Elevation API
=============
Lightweight FastAPI service that returns ground elevation (metres + feet)
for one or many lat/lon coordinates, using the local Copernicus DEM .tif tiles.

Missing tiles are auto-downloaded from OpenTopography (COP30) in the background;
queries for those coordinates return null immediately and succeed on the next call.

Endpoints
---------
GET  /elevation?lat=&lon=          → single point
POST /elevation/batch              → list of {lat, lon} → list of results
GET  /health                       → tile count + pending downloads

Run
---
    uvicorn elevation_api:app --host 0.0.0.0 --port 8011
"""

import asyncio
import glob
import os
import logging
import threading
from typing import Optional, List

import httpx
from fastapi import FastAPI, HTTPException

from pydantic import BaseModel

from elevation import ElevationProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR = os.getenv("ELEVATION_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
COP30_BASE = "https://opentopography.s3.sdsc.edu/raster/COP30/COP30_hh"

# ── Load all .tif tiles at startup ───────────────────────────────────────────
_tif_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.tif")))
if not _tif_files:
    raise RuntimeError(f"No .tif files found in {DATA_DIR}")

providers: List[ElevationProvider] = []
_providers_lock = threading.Lock()

for path in _tif_files:
    try:
        providers.append(ElevationProvider(path))
        logger.info(f"Loaded tile: {os.path.basename(path)}")
    except Exception as e:
        logger.warning(f"Could not load {path}: {e}")

logger.info(f"{len(providers)} elevation tile(s) ready")

# Tracks tiles currently being downloaded (keyed by filename) to avoid duplicates
_pending: set[str] = set()
_pending_lock = threading.Lock()


# ── COP30 tile helpers ────────────────────────────────────────────────────────
def _cop30_filename(lat: float, lon: float) -> str:
    """Return the COP30 filename for the 1°×1° tile covering (lat, lon)."""
    lat_floor = int(lat) if lat >= 0 else int(lat) - 1
    lon_floor = int(lon) if lon >= 0 else int(lon) - 1
    lat_tag = f"N{lat_floor:02d}" if lat_floor >= 0 else f"S{abs(lat_floor):02d}"
    lon_tag = f"E{lon_floor:03d}" if lon_floor >= 0 else f"W{abs(lon_floor):03d}"
    return f"Copernicus_DSM_10_{lat_tag}_00_{lon_tag}_00_DEM.tif"


def _tile_exists_locally(filename: str) -> bool:
    return os.path.isfile(os.path.join(DATA_DIR, filename))


async def _download_tile(filename: str) -> None:
    """Download a COP30 tile and register it with the running providers list."""
    url = f"{COP30_BASE}/{filename}"
    dest = os.path.join(DATA_DIR, filename)
    tmp = dest + ".download"
    logger.info(f"TILE: downloading {filename} …")
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("GET", url) as r:
                if r.status_code == 404:
                    logger.warning(f"TILE: {filename} not found in COP30 (ocean / no data)")
                    # Write a sentinel so we don't retry forever
                    open(dest + ".nodata", "w").close()
                    return
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    async for chunk in r.aiter_bytes(65536):
                        f.write(chunk)
        os.replace(tmp, dest)
        logger.info(f"TILE: {filename} saved ({os.path.getsize(dest) // 1024 // 1024} MB)")
        provider = ElevationProvider(dest)
        with _providers_lock:
            providers.append(provider)
        logger.info(f"TILE: {filename} loaded — {len(providers)} tiles active")
    except Exception as e:
        logger.error(f"TILE: failed to download {filename}: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
    finally:
        with _pending_lock:
            _pending.discard(filename)


def _schedule_download(filename: str) -> None:
    """Fire-and-forget: queue a tile download if not already pending/done."""
    nodata_sentinel = os.path.join(DATA_DIR, filename + ".nodata")
    if _tile_exists_locally(filename) or os.path.exists(nodata_sentinel):
        return
    with _pending_lock:
        if filename in _pending:
            return
        _pending.add(filename)
    logger.info(f"TILE: queuing download for {filename}")
    # asyncio.create_task works when called from an async context (request handler)
    asyncio.create_task(_download_tile(filename))


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Elevation API", version="1.1")


def _query(lat: float, lon: float) -> Optional[float]:
    """Return ground elevation in metres, or None if no tile covers the point."""
    with _providers_lock:
        for p in providers:
            elev = p.get_elevation(lat, lon)
            if elev is not None:
                return elev
    return None


# ── Single point ──────────────────────────────────────────────────────────────
@app.get("/elevation")
async def get_elevation(lat: float, lon: float):
    elev_m = _query(lat, lon)
    if elev_m is None:
        _schedule_download(_cop30_filename(lat, lon))
        raise HTTPException(status_code=404, detail="No elevation data for this location — tile download queued")
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
async def get_elevation_batch(points: List[Point]):
    """
    Returns ground elevation for a list of coordinates.
    Points with no coverage return null values and queue a background tile download.
    """
    results = []
    for p in points:
        elev_m = _query(p.lat, p.lon)
        if elev_m is None:
            _schedule_download(_cop30_filename(p.lat, p.lon))
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
    with _pending_lock:
        pending = list(_pending)
    return {"status": "ok", "tiles_loaded": len(providers), "tiles_downloading": pending}

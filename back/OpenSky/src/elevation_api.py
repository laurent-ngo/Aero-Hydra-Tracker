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


# ── Tiles list (for monitor UI) ───────────────────────────────────────────────
@app.get("/tiles")
def tiles():
    with _providers_lock, _pending_lock:
        loaded = [
            {
                "name": os.path.basename(p.file_path),
                "bounds": {
                    "west":  round(p.bounds.left,  4),
                    "south": round(p.bounds.bottom, 4),
                    "east":  round(p.bounds.right,  4),
                    "north": round(p.bounds.top,    4),
                },
                "status": "loaded",
            }
            for p in providers
        ]
        pending = [{"name": name, "status": "downloading"} for name in _pending]
    return {"tiles": loaded + pending}


# ── Monitor UI ────────────────────────────────────────────────────────────────
_MONITOR_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Elevation Tile Monitor</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;flex-direction:column;height:100vh}
  header{padding:10px 16px;background:#1a1a2e;display:flex;align-items:center;gap:16px;flex-shrink:0}
  header h1{font-size:1rem;font-weight:600;letter-spacing:.05em}
  .pill{font-size:.75rem;padding:2px 8px;border-radius:999px;background:#2a2a4a}
  .pill.loaded{border:1px solid #4ade80;color:#4ade80}
  .pill.downloading{border:1px solid #facc15;color:#facc15;animation:pulse 1s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  #map{flex:1}
  #sidebar{position:absolute;top:56px;right:8px;z-index:1000;width:260px;max-height:calc(100vh - 70px);
           overflow-y:auto;background:#1a1a2ecc;backdrop-filter:blur(4px);
           border:1px solid #333;border-radius:6px;padding:8px;font-size:.72rem}
  #sidebar h2{font-size:.75rem;font-weight:600;margin-bottom:6px;color:#aaa;letter-spacing:.08em}
  .tile-row{padding:3px 4px;border-radius:3px;margin-bottom:2px;cursor:pointer;display:flex;gap:6px;align-items:center}
  .tile-row:hover{background:#ffffff18}
  .dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
  .dot.loaded{background:#4ade80}
  .dot.downloading{background:#facc15;animation:pulse 1s infinite}
  .tile-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #status{font-size:.7rem;color:#888;margin-top:6px;text-align:right}
</style>
</head>
<body>
<header>
  <h1>Elevation Tile Monitor</h1>
  <span class="pill loaded" id="cnt-loaded">— loaded</span>
  <span class="pill downloading" id="cnt-dl" style="display:none">— downloading</span>
</header>
<div id="map"></div>
<div id="sidebar">
  <h2>TILES</h2>
  <div id="tile-list"></div>
  <div id="status">refreshing…</div>
</div>
<script>
const map = L.map('map',{center:[20,10],zoom:2,zoomControl:true});
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{
  attribution:'&copy; OpenStreetMap &copy; CARTO',maxZoom:19
}).addTo(map);

const layers = {};

function styleFor(status){
  return status==='loaded'
    ? {color:'#4ade80',fillColor:'#4ade80',fillOpacity:.15,weight:1}
    : {color:'#facc15',fillColor:'#facc15',fillOpacity:.25,weight:1.5,dashArray:'4 4'};
}

async function refresh(){
  try{
    const r = await fetch('/tiles');
    const {tiles} = await r.json();

    const seen = new Set();
    tiles.forEach(t=>{
      seen.add(t.name);
      if(!t.bounds) return;
      const b = t.bounds;
      const bounds = [[b.south,b.west],[b.north,b.east]];
      if(layers[t.name]){
        layers[t.name].setStyle(styleFor(t.status));
      } else {
        const rect = L.rectangle(bounds, styleFor(t.status))
          .bindTooltip(t.name,{sticky:true})
          .addTo(map);
        layers[t.name] = rect;
      }
    });

    // remove tiles no longer in list
    Object.keys(layers).forEach(name=>{
      if(!seen.has(name)){ map.removeLayer(layers[name]); delete layers[name]; }
    });

    const loaded = tiles.filter(t=>t.status==='loaded').length;
    const dl     = tiles.filter(t=>t.status==='downloading').length;
    document.getElementById('cnt-loaded').textContent = loaded+' loaded';
    const dlPill = document.getElementById('cnt-dl');
    if(dl>0){ dlPill.style.display=''; dlPill.textContent=dl+' downloading'; }
    else { dlPill.style.display='none'; }

    const list = document.getElementById('tile-list');
    list.innerHTML = tiles.map(t=>
      `<div class="tile-row" title="${t.name}">
        <div class="dot ${t.status}"></div>
        <span class="tile-name">${t.name}</span>
       </div>`
    ).join('');

    document.getElementById('status').textContent =
      'updated '+new Date().toLocaleTimeString();
  } catch(e){
    document.getElementById('status').textContent = 'error: '+e.message;
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


@app.get("/monitor", response_class=None)
async def monitor():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_MONITOR_HTML)

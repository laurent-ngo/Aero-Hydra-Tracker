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

# Tiles confirmed to have no COP30 data (ocean) → return elevation 0
_sea_level: set[str] = set()
_sea_level_lock = threading.Lock()

# Load sea-level tiles from existing .nodata sentinels on startup
for _nd in glob.glob(os.path.join(DATA_DIR, "*.nodata")):
    _sea_level.add(os.path.basename(_nd)[:-len(".nodata")])
if _sea_level:
    logger.info(f"{len(_sea_level)} sea-level tile(s) loaded from sentinels")


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


def _bounds_from_cop30_name(filename: str) -> Optional[dict]:
    """Parse lat/lon bounds from a COP30 filename, e.g. Copernicus_DSM_10_N43_00_E004_00_DEM.tif"""
    import re
    m = re.search(r'([NS])(\d+)_00_([EW])(\d+)_00_DEM', filename)
    if not m:
        return None
    lat = int(m.group(2)) * (1 if m.group(1) == 'N' else -1)
    lon = int(m.group(4)) * (1 if m.group(3) == 'E' else -1)
    return {"south": lat, "north": lat + 1, "west": lon, "east": lon + 1}


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
                    logger.warning(f"TILE: {filename} not found in COP30 — marking as sea level")
                    open(dest + ".nodata", "w").close()
                    with _sea_level_lock:
                        _sea_level.add(filename)
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
    with _sea_level_lock:
        if filename in _sea_level:
            return
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
    with _sea_level_lock:
        if _cop30_filename(lat, lon) in _sea_level:
            return 0.0
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
    with _providers_lock, _pending_lock, _sea_level_lock:
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
        sea = [
            {"name": name, "bounds": _bounds_from_cop30_name(name), "status": "sea_level"}
            for name in _sea_level
        ]
    return {"tiles": loaded + pending + sea}


# ── Monitor UI ────────────────────────────────────────────────────────────────
_MONITOR_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Elevation Tile Monitor</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/topojson-client@3/dist/topojson-client.min.js"></script>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;flex-direction:column;height:100vh}
  header{padding:10px 16px;background:#1a1a2e;display:flex;align-items:center;gap:16px;flex-shrink:0}
  header h1{font-size:1rem;font-weight:600;letter-spacing:.05em}
  .pill{font-size:.75rem;padding:2px 8px;border-radius:999px;background:#2a2a4a}
  .pill.loaded{border:1px solid #4ade80;color:#4ade80}
  .pill.downloading{border:1px solid #facc15;color:#facc15;animation:pulse 1s infinite}
  .pill.sea_level{border:1px solid #38bdf8;color:#38bdf8}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  #map{flex:1}
  .leaflet-container{background:#0d1b2a}
  .country-label{background:none;border:none;box-shadow:none;color:#6b8fa8;font-size:9px;
                 white-space:nowrap;pointer-events:none;text-shadow:0 0 3px #0d1b2a}
  #status{font-size:.7rem;color:#888;padding:4px 16px;text-align:right}
</style>
</head>
<body>
<header>
  <h1>Elevation Tile Monitor</h1>
  <span class="pill loaded" id="cnt-loaded">— loaded</span>
  <span class="pill downloading" id="cnt-dl" style="display:none">— downloading</span>
  <span class="pill sea_level" id="cnt-sl" style="display:none">— sea level</span>
</header>
<div id="map"></div>
<div id="status">refreshing…</div>
<script>
const map = L.map('map',{center:[20,10],zoom:2,zoomControl:true});

// ISO numeric → [name, lat, lon]
const COUNTRY_LABELS = {
  '8':[43.5,20.2,'Albania'],'12':[28.0,2.6,'Algeria'],'36':[-25.3,133.8,'Australia'],
  '40':[47.5,14.5,'Austria'],'56':[50.6,4.5,'Belgium'],'64':[27.5,90.4,'Bhutan'],
  '68':[-16.3,-63.6,'Bolivia'],'76':[-14.2,-51.9,'Brazil'],'100':[42.7,25.5,'Bulgaria'],
  '116':[12.6,104.9,'Cambodia'],'120':[5.7,12.3,'Cameroon'],'124':[56.1,-106.3,'Canada'],
  '140':[6.6,20.9,'C.A.R.'],'144':[7.9,80.8,'Sri Lanka'],'152':[-35.7,-71.5,'Chile'],
  '156':[35.9,104.2,'China'],'170':[4.1,-72.3,'Colombia'],'191':[45.1,15.2,'Croatia'],
  '196':[35.1,33.4,'Cyprus'],'203':[49.8,15.5,'Czechia'],'208':[56.3,9.5,'Denmark'],
  '818':[26.8,30.8,'Egypt'],'233':[58.6,25.0,'Estonia'],'231':[9.1,40.5,'Ethiopia'],
  '246':[64.0,26.0,'Finland'],'250':[46.2,2.2,'France'],'276':[51.2,10.4,'Germany'],
  '288':[7.9,-1.0,'Ghana'],'300':[39.1,22.0,'Greece'],'320':[15.8,-90.2,'Guatemala'],
  '191':[45.1,15.2,'Croatia'],'191':[45.1,15.2,'Croatia'],
  '348':[47.2,19.5,'Hungary'],'356':[20.6,78.9,'India'],'360':[-0.8,113.9,'Indonesia'],
  '364':[32.4,53.7,'Iran'],'368':[33.2,43.7,'Iraq'],'372':[53.1,-8.2,'Ireland'],
  '376':[31.1,34.9,'Israel'],'380':[42.8,12.6,'Italy'],'392':[36.2,138.3,'Japan'],
  '400':[31.2,36.5,'Jordan'],'398':[48.0,66.9,'Kazakhstan'],'404':[-0.0,37.9,'Kenya'],
  '410':[36.6,127.9,'South Korea'],'414':[29.3,47.5,'Kuwait'],'422':[33.9,35.5,'Lebanon'],
  '434':[27.0,17.2,'Libya'],'440':[55.9,23.9,'Lithuania'],'442':[49.8,6.1,'Luxembourg'],
  '450':[-20.3,46.9,'Madagascar'],'484':[23.6,-102.5,'Mexico'],'504':[31.8,-7.1,'Morocco'],
  '528':[52.3,5.3,'Netherlands'],'554':[-40.9,174.9,'New Zealand'],
  '566':[9.1,8.7,'Nigeria'],'578':[60.5,8.5,'Norway'],'512':[21.5,55.9,'Oman'],
  '586':[30.4,69.3,'Pakistan'],'275':[31.9,35.2,'Palestine'],'591':[8.5,-80.8,'Panama'],
  '604':[-9.2,-75.0,'Peru'],'608':[12.9,121.8,'Philippines'],'616':[52.1,19.1,'Poland'],
  '620':[39.4,-8.2,'Portugal'],'634':[25.4,51.2,'Qatar'],'642':[45.9,24.9,'Romania'],
  '643':[61.5,105.3,'Russia'],'682':[24.2,45.1,'Saudi Arabia'],'686':[14.5,-14.5,'Senegal'],
  '694':[8.5,-11.8,'Sierra Leone'],'703':[48.7,19.7,'Slovakia'],'705':[46.2,14.8,'Slovenia'],
  '706':[6.0,46.2,'Somalia'],'710':[-30.6,22.9,'South Africa'],'724':[40.5,-3.7,'Spain'],
  '729':[15.6,32.5,'Sudan'],'752':[60.1,18.6,'Sweden'],'756':[47.0,8.2,'Switzerland'],
  '760':[34.8,38.9,'Syria'],'762':[38.9,71.3,'Tajikistan'],'764':[15.9,100.9,'Thailand'],
  '788':[34.0,9.0,'Tunisia'],'792':[38.9,35.2,'Turkey'],'800':[1.4,32.3,'Uganda'],
  '804':[49.0,31.4,'Ukraine'],'784':[24.0,54.0,'UAE'],'826':[55.4,-3.4,'UK'],
  '840':[37.1,-95.7,'USA'],'858':[-32.5,-55.8,'Uruguay'],'860':[41.4,64.6,'Uzbekistan'],
  '862':[6.4,-66.6,'Venezuela'],'704':[14.1,108.3,'Vietnam'],
  '887':[15.9,47.6,'Yemen'],'894':[-14.1,27.9,'Zambia'],'716':[-20.0,30.0,'Zimbabwe'],
  '262':[11.8,42.6,'Djibouti'],'450':[-20.3,46.9,'Madagascar'],
  '462':[3.2,73.2,'Maldives'],'480':[-20.3,57.6,'Mauritius'],
};

// Countries go in a pane below the overlay pane so tile rectangles always appear on top
map.createPane('countries');
map.getPane('countries').style.zIndex = 250;
map.getPane('countries').style.pointerEvents = 'none';

fetch('https://unpkg.com/world-atlas@2/countries-110m.json')
  .then(r=>r.json())
  .then(world=>{
    const countries = topojson.feature(world, world.objects.countries);
    L.geoJSON(countries,{
      pane:'countries',
      style:{color:'#2a3f55',weight:0.7,fillColor:'#152030',fillOpacity:1}
    }).addTo(map);

    // Add country name labels
    countries.features.forEach(f=>{
      const info = COUNTRY_LABELS[f.id];
      if(!info) return;
      const [lat,lon,name] = info;
      L.marker([lat,lon],{
        icon:L.divIcon({className:'country-label',html:name,iconAnchor:[0,0]}),
        interactive:false,keyboard:false
      }).addTo(map);
    });
  });

const layers = {};

function styleFor(status){
  if(status==='loaded')    return {color:'#4ade80',fillColor:'#4ade80',fillOpacity:.15,weight:1};
  if(status==='sea_level') return {color:'#38bdf8',fillColor:'#38bdf8',fillOpacity:.12,weight:0.6};
  return {color:'#facc15',fillColor:'#facc15',fillOpacity:.25,weight:1.5,dashArray:'4 4'};
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
    const sl     = tiles.filter(t=>t.status==='sea_level').length;
    document.getElementById('cnt-loaded').textContent = loaded+' loaded';
    const dlPill = document.getElementById('cnt-dl');
    if(dl>0){ dlPill.style.display=''; dlPill.textContent=dl+' downloading'; }
    else { dlPill.style.display='none'; }
    const slPill = document.getElementById('cnt-sl');
    if(sl>0){ slPill.style.display=''; slPill.textContent=sl+' sea level'; }
    else { slPill.style.display='none'; }

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

import requests
import os
from datetime import datetime
import time
import logging
logger = logging.getLogger(__name__)


class FirefleetCollector:
    def __init__(self, token):
        self.url = "https://opensky-network.org/api/states/all"
        self.track_url = "https://opensky-network.org/api/tracks/all"

        self.app_json = "application/json"

        self.default_bbox = {}


         # ~1400 km2
        self.default_bbox['lamin'] = 35.5
        self.default_bbox['lomin'] = -4.8
        self.default_bbox['lamax'] = 52.09
        self.default_bbox['lomax'] = 19

        self.token = token

    def get_positions(self, icao_list):
        # Construct the query parameters
        params = [('callsign', icao) for icao in icao_list]

        params.extend([
            ('lamin', self.default_bbox['lamin']),
            ('lomin', self.default_bbox['lomin']),
            ('lamax', self.default_bbox['lamax']),
            ('lomax', self.default_bbox['lomax'])
        ])

        
        # New Header Format for OAuth2 / JWT
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": self.app_json
        }
        
        try:
            logger.info( "Calling OpenSky API/states")
            response = requests.get(
                self.url, 
                headers=headers, # Switched from auth= to headers=
                params=params, 
                timeout=15
            )
            response.raise_for_status()
            
            data = response.json()
            logger.debug("Successfully connected to OpenSky!")
            return data.get('states', [])

        except requests.exceptions.HTTPError as e:
            logger.error(f"Auth Error: {e.response.status_code} - Check if the token has expired.")
            return []

    def get_by_icao24(self, icao_list):
        # Force everything to lowercase to meet OpenSky requirements
        clean_icao = [str(icao).lower() for icao in icao_list]
        
        # Construct the query parameters correctly
        params = [('icao24', icao) for icao in clean_icao]
        
        params.extend([
            ('lamin', self.default_bbox['lamin']),
            ('lomin', self.default_bbox['lomin']),
            ('lamax', self.default_bbox['lamax']),
            ('lomax', self.default_bbox['lomax'])
        ])

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": self.app_json
        }
        
        try:
            logger.info( "Calling OpenSky API/states")
            response = requests.get(
                self.url, 
                headers=headers, 
                params=params, 
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
                
            states = data.get('states', [])

            if states == None:
                logger.info( "No active aircraft...")
                return []
            
            # Filtering in Python
            # Callsigns in OpenSky are 8 chars long, often padded with spaces
            matched_fleet = []
            for s in states:
                raw_icao24 = s[0].strip()
                if raw_icao24 in clean_icao:
                    matched_fleet.append({
                        "icao24": raw_icao24,
                        "callsign": s[1],
                        "country": s[2],
                        "lat": s[6],
                        "lon": s[5],
                        "alt": s[7]
                    })
            return matched_fleet
        
        except Exception as e:
            logger.error(f"{e}")
            return []
    
    def get_by_callsigns(self, target_callsigns):
            """Fetches all states and filters by a list of callsigns."""
            headers = {"Authorization": f"Bearer {self.token}"}
            
            try:
                # We fetch all (or use a bounding box for FinOps efficiency)
                logger.info( "Calling OpenSky API/states")
                response = requests.get(
                    self.url, 
                    headers=headers, 
                    timeout=15
                )
                response.raise_for_status()
                data = response.json()
                
                states = data.get('states', [])
                
                # Filtering in Python
                # Callsigns in OpenSky are 8 chars long, often padded with spaces
                matched_fleet = []
                for s in states:
                    raw_callsign = s[1].strip()
                    if raw_callsign in target_callsigns:
                        matched_fleet.append({
                            "icao24": s[0],
                            "callsign": raw_callsign,
                            "country": s[2],
                            "lat": s[6],
                            "lon": s[5],
                            "alt": s[7]
                        })
                return matched_fleet

            except Exception as e:
                logger.error(f"{e}")
                return []
            
    def get_aircraft_track(self, icao24, target_time=0):
        """
        Fetches the track for a specific aircraft at a specific time.
        target_time: Python datetime object or UNIX timestamp
        """
        params = {
            'icao24': icao24.lower(),
            'time': target_time
        }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": self.app_json
        }

        try:
            logger.info( "Calling OpenSky API/track")
            response = requests.get(
                self.track_url, 
                headers=headers, 
                params=params, 
                timeout=15
                )
            response.raise_for_status()

            return response.json() # Returns a full track object with path points
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error(f"Too many requests, Quota exceeded: {e}")
            elif e.response.status_code != 404:
                logger.error(f"HTTP Error fetching track for {icao24}: {e}")
            return None
        except Exception as e:
            # Catch non-HTTP errors like timeouts or connection issues
            logger.error(f"Unexpected error fetching track for {icao24}: {e}")
            return None

class AdsbV2Collector:
    """Generic collector for any ADSBexchange v2 compatible API."""
    
    SOURCES = {
        'adsbfi':       'https://opendata.adsb.fi/api',
        'airplaneslive':'https://api.airplanes.live/v2',
        'adsbonelol':   'https://api.adsb.lol/v2',
        'adsboneapi':   'https://api.adsb.one/v2',
    }

    def __init__(self, source='adsbfi'):
        if source not in self.SOURCES:
            raise ValueError(f"Unknown source '{source}'. Choose from: {list(self.SOURCES)}")
        self.source = source
        self.base_url = self.SOURCES[source]

    def get_by_icao24(self, icao_list):
        clean_icao = {icao.lower() for icao in icao_list}
        if self.source == 'adsbfi':
            url = f"https://opendata.adsb.fi/api/v2/icao/{','.join(clean_icao)}"
        else:
            url = f"{self.base_url}/icao/{','.join(clean_icao)}"

        try:
            logger.info(f"Calling {self.source} API")
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            aircraft = response.json().get('ac', [])

            results = {}
            for ac in aircraft:
                icao24 = str(ac.get('hex', '')).lower().strip()
                if icao24 not in clean_icao:
                    continue
                lat, lon = ac.get('lat'), ac.get('lon')
                if lat is None or lon is None:
                    continue
                baro_alt = ac.get('alt_baro')
                results[icao24] = {
                    'icao24':     icao24,
                    'timestamp':  int(time.time()) - int(ac.get('seen', 0) or 0),
                    'lat':        lat,
                    'lon':        lon,
                    'baro_alt':   baro_alt if baro_alt != 'ground' else None,
                    'on_ground':  baro_alt == 'ground',
                    'true_track': ac.get('track'),
                    'velocity':   ac.get('gs'),
                    'source':     self.source,
                }

            logger.info(f"{self.source} returned {len(results)} tracked aircraft")
            return results

        except Exception as e:
            logger.error(f"{self.source} error: {e}")
            return {}

    def scan_by_area(self, lat, lon, radius_nm=500, model_keywords=None, type_codes=None, blacklist=None):

        if self.source == 'adsbfi':
            url = f"https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{min(radius_nm, 250)}"
        elif self.source == 'adsboneapi':
            url = f"https://api.adsb.one/v2/point/{lat}/{lon}/{radius_nm}"
        else:
            url = f"{self.base_url}/lat/{lat}/lon/{lon}/dist/{radius_nm}"
    
        blacklist_set = {icao.lower() for icao in (blacklist or [])}
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            aircraft = response.json().get('ac', [])

            results = []
            for ac in aircraft:
                icao24     = ac.get('hex', '').lower()
                if icao24 in blacklist_set:
                    continue
                icao_type  = ac.get('t', '') or ''
                desc       = ac.get('desc', '') or ''
                reg        = ac.get('r', '') or ''
                searchable = f"{icao_type} {desc}".lower()

                match = False
                if model_keywords:
                    match = any(kw.lower() in searchable for kw in model_keywords)
                if type_codes and not match:
                    match = any(icao_type.upper().startswith(tc.upper()) for tc in type_codes)

                if not model_keywords and not type_codes:
                    match = True

                if match:
                    results.append({
                        'icao24':    icao24,
                        'reg':       reg,
                        'model':     desc or icao_type,
                        'icao_type': icao_type,
                        'flight': (ac.get('flight', '') or '').strip(),
                        'lat':       ac.get('lat'),
                        'lon':       ac.get('lon'),
                        'alt_ft':    ac.get('alt_baro'),
                        'track':     ac.get('track'),
                        'source':    self.source,
                    })

            logger.info(f"[{self.source}] Area scan: {len(results)} new matching aircraft out of {len(aircraft)} total ({len(blacklist_set)} blacklisted)")
            return results

        except Exception as e:
            logger.error(f"[{self.source}] Area scan error: {e}")
            return []

class FR24Collector:
    def __init__(self):
        self.api_key  = os.getenv('FR24_API_KEY')
        self.base_url = 'https://fr24api.flightradar24.com/api'
        self.headers  = {
            'Accept':        'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

    def get_by_icao24(self, icao_list):
        """Fetch latest position for a list of ICAO24s using the light endpoint."""
        clean_icao = {icao.lower() for icao in icao_list}

        # FR24 uses hex field — build comma-separated list
        hex_param = ','.join(clean_icao)
        url = f"{self.base_url}/live/flight-positions/light"

        try:
            logger.info("Calling FR24 API/positions")
            response = requests.get(
                url,
                headers=self.headers,
                params={'hex': hex_param},
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            aircraft = data.get('data', [])

            results = {}
            for ac in aircraft:
                icao24 = str(ac.get('hex', '')).lower().strip()
                if icao24 not in clean_icao:
                    continue
                lat = ac.get('lat')
                lon = ac.get('lon')
                if lat is None or lon is None:
                    continue

                # FR24 timestamp is ISO8601 — convert to unix
                ts_str = ac.get('timestamp')
                try:
                    from datetime import datetime, timezone
                    ts = int(datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp())
                except Exception:
                    ts = int(time.time())

                baro_alt = ac.get('alt')

                results[icao24] = {
                    'icao24':     icao24,
                    'timestamp':  ts,
                    'lat':        lat,
                    'lon':        lon,
                    'baro_alt':   round(baro_alt / 3.28084, 1) if baro_alt is not None else None,  # ft → metres
                    'on_ground':  baro_alt == 0,
                    'true_track': ac.get('track'),
                    'velocity':   ac.get('gspeed'),
                    'source':     'fr24',
                }

            logger.info(f"FR24 returned {len(results)} tracked aircraft")
            return results

        except Exception as e:
            logger.error(f"FR24 error: {e}")
            return {}

    def get_track(self, icao24, fr24_id=None):
        """
        Fetch full 30-day track for a specific aircraft.
        Requires fr24_id — use get_fr24_id() first if unknown.
        """
        if not fr24_id:
            fr24_id = self.get_fr24_id(icao24)
        if not fr24_id:
            logger.warning(f"[{icao24}] No FR24 ID found, cannot fetch track.")
            return []

        url = f"{self.base_url}/historic/flight-tracks/{fr24_id}"

        try:
            logger.info(f"Calling FR24 API/track for {icao24} ({fr24_id})")
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            tracks = data.get('tracks', [])

            points = []
            for p in tracks:
                ts_str = p.get('timestamp')
                try:
                    from datetime import datetime, timezone
                    ts = int(datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp())
                except Exception:
                    continue

                alt_ft = p.get('alt')
                alt_m  = round(alt_ft / 3.28084, 1) if alt_ft is not None else None

                # Format matches bulk_insert_telemetry: [ts, lat, lon, alt_m, track, on_ground]
                points.append([
                    ts,
                    p.get('lat'),
                    p.get('lon'),
                    alt_m,
                    p.get('track'),
                    alt_ft == 0,
                ])

            logger.info(f"FR24 track for {icao24}: {len(points)} points")
            return points

        except Exception as e:
            logger.error(f"FR24 track error for {icao24}: {e}")
            return []

    def get_fr24_id(self, icao24):
        """Resolve an ICAO24 hex to a FR24 flight ID via the light endpoint."""
        results = self.get_by_icao24([icao24])
        return results.get(icao24, {}).get('fr24_id')


# --- Local Test ---
if __name__ == "__main__":
    # In Github, we will use os.getenv('OPENSKY_CLIENT_TOKEN')
    TOKEN = os.getenv('OPENSKY_CLIENT_TOKEN')

    logger.debug(f"Token found: {'Yes' if TOKEN else 'No'}")

    collector = FirefleetCollector(TOKEN)
    adsb_fi = AdsbV2Collector('adsbfi')
    airplaneslive = AdsbV2Collector('airplaneslive')
    adsbonelol = AdsbV2Collector('adsbonelol')

       
    MY_CALLSIGNS = ["MILAN7V"] # Example water bombers
    
    # All Canadair and Dash (Securité civile)
    MY_ICAO24S = ["39856F", "3b7b39", "3b7b6c" ]

    # For test
    #fleet_status = collector.get_by_callsigns(MY_CALLSIGNS)
    opensky_states = collector.get_by_icao24(MY_ICAO24S)
    adsb_fi_results = adsb_fi.get_by_icao24(MY_ICAO24S)
    airplaneslive_results = airplaneslive.get_by_icao24(MY_ICAO24S)
    adsbonelol_results = adsbonelol.get_by_icao24(MY_ICAO24S)
    
    print(opensky_states)
    print(adsb_fi_results)
    print(airplaneslive_results)
    print(adsbonelol_results)
    
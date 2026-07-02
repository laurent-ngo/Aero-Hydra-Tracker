import re
import requests
import os
from datetime import datetime
import time
import logging
logger = logging.getLogger(__name__)

# FR24 only accepts standard civil registrations: must start with a letter,
# contain only letters, digits, and hyphens (no dots, no all-numeric).
_FR24_REG_RE = re.compile(r'^[A-Za-z][A-Za-z0-9-]+$')


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
            'Accept':         'application/json',
            'Accept-Version': 'v1',
            'Authorization':  f'Bearer {self.api_key}'
        }

    def get_by_registrations(self, reg_to_icao):
        """
        Fetch live positions filtered by aircraft registration.
        reg_to_icao: {registration: icao24} dict
        Returns: {icao24: {...}} — same shape as AdsbV2Collector.
        FR24 /live/flight-positions/light does not support hex filtering;
        registrations (max 15 per request) is the correct filter.
        """
        all_regs = list(reg_to_icao.keys())
        registrations = [r for r in all_regs if _FR24_REG_RE.match(r)]
        skipped = len(all_regs) - len(registrations)
        if skipped:
            logger.info(f"FR24: skipping {skipped} registrations with unsupported format "
                        f"({[r for r in all_regs if not _FR24_REG_RE.match(r)]})")
        icao_lower = {icao.lower() for icao in reg_to_icao.values()}
        url = f"{self.base_url}/live/flight-positions/light"
        results = {}

        for i in range(0, len(registrations), 20):
            if i > 0:
                time.sleep(7)
            batch = registrations[i:i + 20]
            batch_num = i // 15 + 1
            try:
                logger.info(f"Calling FR24 API/positions (batch {batch_num})")
                response = requests.get(
                    url,
                    headers=self.headers,
                    params={'registrations': ','.join(batch)},
                    timeout=15
                )
                response.raise_for_status()
                self._parse_positions(response.json().get('data', []), icao_lower, results)
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status == 400:
                    # One invalid registration poisons the whole batch — retry individually
                    logger.warning(f"FR24 batch {batch_num} rejected (400), retrying individually...")
                    for reg in batch:
                        try:
                            r = requests.get(url, headers=self.headers,
                                             params={'registrations': reg}, timeout=15)
                            r.raise_for_status()
                            self._parse_positions(r.json().get('data', []), icao_lower, results)
                        except Exception as e2:
                            logger.info(f"FR24 skipped registration '{reg}': {e2}")
                        time.sleep(0.5)
                elif status in (429,) or (status is not None and status >= 500):
                    retry_after = int(e.response.headers.get('Retry-After', 60))
                    logger.warning(f"FR24 batch {batch_num} got {status}, retrying after {retry_after}s...")
                    time.sleep(retry_after)
                    try:
                        r = requests.get(url, headers=self.headers,
                                         params={'registrations': ','.join(batch)}, timeout=15)
                        r.raise_for_status()
                        self._parse_positions(r.json().get('data', []), icao_lower, results)
                    except Exception as e2:
                        logger.error(f"FR24 batch {batch_num} retry failed: {e2}")
                else:
                    logger.error(f"FR24 error (batch {batch_num}): {e}")
            except Exception as e:
                logger.error(f"FR24 error (batch {batch_num}): {e}")

        logger.info(f"FR24 returned {len(results)} tracked aircraft")
        return results

    def _parse_positions(self, aircraft_list, icao_lower, results):
        """Parse a list of FR24 position dicts into the results dict (keyed by icao24)."""
        for ac in aircraft_list:
            icao24 = str(ac.get('hex', '') or '').lower().strip()
            if not icao24 or icao24 not in icao_lower:
                continue
            lat, lon = ac.get('lat'), ac.get('lon')
            if lat is None or lon is None:
                continue
            ts_str = ac.get('timestamp')
            try:
                from datetime import datetime, timezone
                ts = int(datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp())
            except Exception:
                ts = int(time.time())
            alt_ft = ac.get('alt')
            results[icao24] = {
                'icao24':     icao24,
                'fr24_id':    ac.get('fr24_id'),
                'timestamp':  ts,
                'lat':        lat,
                'lon':        lon,
                'baro_alt':   round(alt_ft / 3.28084, 1) if alt_ft is not None else None,
                'on_ground':  alt_ft == 0,
                'true_track': ac.get('track'),
                'velocity':   ac.get('gspeed'),
                'source':     'fr24',
            }

    def get_track(self, icao24, fr24_id=None):
        """Fetch positional track for a specific FR24 flight ID."""
        if not fr24_id:
            logger.warning(f"[{icao24}] No FR24 flight ID, cannot fetch track.")
            return []

        try:
            logger.info(f"Calling FR24 API/flight-tracks for {icao24} ({fr24_id})")
            response = requests.get(
                f"{self.base_url}/flight-tracks",
                headers=self.headers,
                params={'flight_id': fr24_id},
                timeout=15
            )
            response.raise_for_status()
            body = response.json()
            tracks = body if isinstance(body, list) else body.get('tracks', [])
            logger.debug(f"FR24 track raw: type={type(body).__name__}, {len(tracks)} entries, sample={tracks[0] if tracks else 'empty'}")

            points = []
            for p in tracks:
                ts_str = p.get('timestamp')
                try:
                    from datetime import datetime, timezone
                    ts = int(datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp())
                except Exception as ts_err:
                    logger.debug(f"FR24 track timestamp parse failed for {icao24}: ts_str={ts_str!r} err={ts_err}")
                    continue
                alt_ft = p.get('alt')
                alt_m  = round(alt_ft / 3.28084, 1) if alt_ft is not None else None
                points.append([ts, p.get('lat'), p.get('lon'), alt_m, p.get('track'), alt_ft == 0])

            logger.info(f"FR24 track for {icao24}: {len(points)} points")
            return points

        except Exception as e:
            logger.error(f"FR24 track error for {icao24}: {e}")
            return []


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
    
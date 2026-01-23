import requests
import os


class FirefleetCollector:
    def __init__(self, token):
        self.url = "https://opensky-network.org/api/states/all"
        self.token = token

    def get_positions(self, icao_list):
        # Construct the query parameters
        params = [('callsign', icao) for icao in icao_list]
        
        # New Header Format for OAuth2 / JWT
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }
        
        try:
            response = requests.get(
                self.url, 
                headers=headers, # Switched from auth= to headers=
                params=params, 
                timeout=15
            )
            response.raise_for_status()
            
            data = response.json()
            print("Successfully connected to OpenSky!")
            return data.get('states', [])

        except requests.exceptions.HTTPError as e:
            print(f"Auth Error: {e.response.status_code} - Check if the token has expired.")
            return []

    def get_by_callsigns(self, target_callsigns):
            """Fetches all states and filters by a list of callsigns."""
            headers = {"Authorization": f"Bearer {self.token}"}
            
            try:
                # We fetch all (or use a bounding box for FinOps efficiency)
                response = requests.get(self.url, headers=headers, timeout=15)
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
                            "lat": s[6],
                            "lon": s[5],
                            "alt": s[7]
                        })
                return matched_fleet

            except Exception as e:
                print(f"Error: {e}")
                return []
            
# --- Local Test ---
if __name__ == "__main__":
    # In GitLab, we will use os.getenv('OPENSKY_CLIENT_SECRET')
    TOKEN = os.getenv('OPENSKY_CLIENT_SECRET')

    print(f"DEBUG: Token found: {'Yes' if TOKEN else 'No'}")
    
    MY_CALLSIGNS = ["FRBAQ", "PHBVK", "N937MA", "CAT724"] # Example water bombers

    collector = FirefleetCollector(TOKEN)
    fleet_status = collector.get_by_callsigns(MY_CALLSIGNS)(MY_CALLSIGNS)
    
    for plane in fleet_status:
        print(f"Unit {plane}")
import requests
import os


class FirefleetCollector:
    def __init__(self, token):
        self.url = "https://opensky-network.org/api/states/all"
        self.token = token

    def get_positions(self, icao_list):
        # Construct the query parameters
        params = [('icao24', icao) for icao in icao_list]
        
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

# --- Local Test ---
if __name__ == "__main__":
    # In GitLab, we will use os.getenv('OPENSKY_CLIENT_SECRET')
    TOKEN = os.getenv('OPENSKY_CLIENT_SECRET')

    print(f"DEBUG: Token found: {'Yes' if TOKEN else 'No'}")
    
    ICAO_TARGETS = ["3b760a", "3b760b"] # Example water bombers

    collector = FirefleetCollector(TOKEN)
    fleet_status = collector.get_positions(ICAO_TARGETS)
    
    for plane in fleet_status:
        print(f"Unit {plane['icao24']} | Alt: {plane['alt']}m | Spd: {plane['velocity']}m/s")
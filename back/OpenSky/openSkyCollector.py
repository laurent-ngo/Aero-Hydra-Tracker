import requests
import time

class OpenSkyCollector:
    def __init__(self, icao_list):
        self.url = "https://opensky-network.org/api/states/all"
        self.fleet = icao_list

    def fetch_fleet_status(self):
        # We query by specific ICAO24 hex codes
        params = {'icao24': self.fleet}
        
        try:
            response = requests.get(self.url, params=params, timeout=10)
            response.raise_for_status() # Diplomatic handling of API errors
            data = response.json()
            
            states = data.get('states')
            if not states:
                print("No active flights found for the specified fleet.")
                return []

            extracted_data = []
            for s in states:
                # Mapping OpenSky indices to readable names
                plane_data = {
                    "icao24": s[0],
                    "callsign": s[1].strip() if s[1] else "N/A",
                    "longitude": s[5],
                    "latitude": s[6],
                    "baro_altitude": s[7], # Altitude in metres
                    "velocity": s[9],      # Speed in m/s
                    "last_contact": s[4]
                }
                extracted_data.append(plane_data)
            
            return extracted_data

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data: {e}")
            return []

# --- Usage ---
if __name__ == "__main__":
    # Example ICAO24s for common water bombers (e.g., Canadair CL-415)
    # You will replace these with your actual list
    MY_FLEET = ["FRAFR" ] 
    
    collector = OpenSkyCollector(MY_FLEET)
    results = collector.fetch_fleet_status()

    for plane in results:
        print(f"Found {plane['icao24']} ({plane['callsign']}) at {plane['latitude']}, {plane['longitude']}")
        print(f"  > Altitude: {plane['baro_altitude']}m | Speed: {plane['velocity']}m/s\n")
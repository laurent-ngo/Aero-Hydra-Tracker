import math
import migrate
import requests
import os
import time
import logging
import rasterio
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class ElevationProvider:
    def __init__(self, file_path="../data/output_hh.tif"):
        self.file_path = file_path
        self.dataset = rasterio.open(self.file_path)

        self.bounds = self.dataset.bounds
        logger.info(f"ElevationProvider initialized with {file_path}")

    def get_elevation(self, lat: float, lon: float) -> Optional[float]:
        """Returns elevation in meters for a given lat/lon."""
        try:
            # 1. Quick boundary check to avoid errors
            if not (self.bounds.left <= lon <= self.bounds.right and 
                    self.bounds.bottom <= lat <= self.bounds.top):
                return -100000 # to differentiate out of bound from umprocessed

            # 2. Get the pixel coordinates (row, col) from lat/lon
            # rasterio.index takes (longitude, latitude)
            row, col = self.dataset.index(lon, lat)

            # 3. Read only the specific pixel (1x1 window) for speed
            # This is much faster than reading the whole band
            window = rasterio.windows.Window(col, row, 1, 1)
            data = self.dataset.read(1, window=window)
            
            return float(data[0, 0])
            
        except Exception as e:
            # Silent fail for points slightly outside or edge cases
            return None

    def close(self):
        """Cleanly close the file handle."""
        self.dataset.close()

# --- Local Test ---
if __name__ == "__main__":

    elevation = ElevationProvider()

    print( elevation.get_elevation( 43.7533, 4.4166) ) #298 ft
    print( elevation.get_elevation( 43.7118, 4.4194) ) #210 ft


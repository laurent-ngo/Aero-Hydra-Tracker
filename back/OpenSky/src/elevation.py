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
        # Open briefly to read bounds only; no persistent file handle kept.
        with rasterio.open(self.file_path) as ds:
            self.bounds = ds.bounds
        logger.info(f"ElevationProvider initialized with {file_path}")

    def get_elevation(self, lat: float, lon: float) -> Optional[float]:
        """Returns elevation in meters for a given lat/lon."""
        try:
            if not (self.bounds.left <= lon <= self.bounds.right and
                    self.bounds.bottom <= lat <= self.bounds.top):
                return None

            with rasterio.open(self.file_path) as ds:
                row, col = ds.index(lon, lat)
                window = rasterio.windows.Window(col, row, 1, 1)
                data = ds.read(1, window=window)

            return float(data[0, 0])

        except Exception:
            return None

    def close(self):
        pass

# --- Local Test ---
if __name__ == "__main__":

    elevation = ElevationProvider()

    print( elevation.get_elevation( 43.7533, 4.4166) ) #298 ft
    print( elevation.get_elevation( 43.7118, 4.4194) ) #210 ft


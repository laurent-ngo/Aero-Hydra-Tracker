# back/OpenSky/test/conftest.py
import sys
import os
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

# Mock all unavailable dependencies
sys.modules['psycopg2']            = MagicMock()
sys.modules['psycopg2.extensions'] = MagicMock()
sys.modules['rasterio']            = MagicMock()
sys.modules['rasterio.windows']    = MagicMock()
sys.modules['sklearn']             = MagicMock()
sys.modules['sklearn.cluster']     = MagicMock()
sys.modules['scipy']               = MagicMock()
sys.modules['scipy.spatial']       = MagicMock()
sys.modules['shapely']             = MagicMock()
sys.modules['shapely.geometry']    = MagicMock()
sys.modules['shapely.ops']         = MagicMock()
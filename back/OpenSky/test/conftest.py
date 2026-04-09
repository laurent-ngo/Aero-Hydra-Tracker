# back/OpenSky/test/conftest.py
import sys
import os
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

# Mock all heavy/unavailable dependencies
sys.modules['psycopg2']            = MagicMock()
sys.modules['psycopg2.extensions'] = MagicMock()
sys.modules['rasterio']            = MagicMock()
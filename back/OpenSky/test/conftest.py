# back/OpenSky/test/conftest.py
import sys
import os
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../src'))

# Mock psycopg2 and sqlalchemy engine before any src module is imported
sys.modules['psycopg2'] = MagicMock()
sys.modules['psycopg2.extensions'] = MagicMock()
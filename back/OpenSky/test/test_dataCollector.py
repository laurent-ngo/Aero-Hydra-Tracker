import pytest
import json
import os
from unittest.mock import patch, mock_open, MagicMock

# Assuming the function is in dataCollector.py
from dataCollector import get_cached_icao_list, CACHE_FILE


def test_returns_none_when_cache_file_missing():
    with patch('os.path.exists', return_value=False):
        result = get_cached_icao_list()
    assert result is None


def test_returns_icao_list_when_cache_exists():
    icao_list = ['3b7b39', '3b7b63', '3b7b86']
    with patch('os.path.exists', return_value=True), \
         patch('builtins.open', mock_open(read_data=json.dumps(icao_list))):
        result = get_cached_icao_list()
    assert result == icao_list


def test_returns_none_when_cache_file_is_invalid_json():
    with patch('os.path.exists', return_value=True), \
         patch('builtins.open', mock_open(read_data='not valid json')):
        result = get_cached_icao_list()
    assert result is None


def test_returns_none_when_file_read_raises_exception():
    with patch('os.path.exists', return_value=True), \
         patch('builtins.open', side_effect=IOError('permission denied')):
        result = get_cached_icao_list()
    assert result is None


def test_returns_empty_list_when_cache_is_empty():
    with patch('os.path.exists', return_value=True), \
         patch('builtins.open', mock_open(read_data='[]')):
        result = get_cached_icao_list()
    assert result == []
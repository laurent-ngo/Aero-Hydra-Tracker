import pytest
import requests_mock
from openSkyCollector import FirefleetCollector

@pytest.fixture
def collector():
    return FirefleetCollector("fake_test_token")

def test_get_by_callsigns_success(collector):
    # Mocking the OpenSky JSON response
    mock_data = {
        "states": [
            ["3b760a", "FRBAQ   ", "France", 1721832000, 1721832000, 5.2, 43.1, 1500, False, 100, 0, 0, None, 1500, "1234", False, 0],
            ["abcd12", "OTHER1  ", "USA", 1721832000, 1721832000, -122.1, 37.4, 5000, False, 200, 0, 0, None, 5000, "5678", False, 0]
        ]
    }

    with requests_mock.Mocker() as m:
        m.get("https://opensky-network.org/api/states/all", json=mock_data)
        
        results = collector.get_by_callsigns(["FRBAQ"])
        
        assert len(results) == 1
        assert results[0]["callsign"] == "FRBAQ"
        assert results[0]["icao24"] == "3b760a"

def test_get_by_callsigns_empty_on_error(collector):
    with requests_mock.Mocker() as m:
        m.get("https://opensky-network.org/api/states/all", status_code=401)
        
        results = collector.get_by_callsigns(["FRBAQ"])
        assert results == []
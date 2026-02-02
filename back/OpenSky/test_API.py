import pytest
from httpx import AsyncClient
from main import app # Import your FastAPI app instance

@pytest.mark.asyncio
async def test_get_aircraft_list():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/aircraft")
    
    assert response.status_code == 200
    data = response.json()
    
    if len(data) > 0:
        # Check if our new flags are present in the response
        first_ac = data[0]
        assert "at_airfield" in first_ac
        assert "is_full" in first_ac
        assert isinstance(first_ac["at_airfield"], bool)

@pytest.mark.asyncio
async def test_telemetry_valid_icao():
    test_icao = "4b1805" # Use a known ICAO from your DB
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get(f"/telemetry/{test_icao}")
    
    assert response.status_code == 200
    assert isinstance(response.json(), list)
from fastapi import FastAPI, Depends, HTTPException, Query, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional
from typing import Annotated, Optional

import migrate # Importing your existing models and SessionLocal
import time, os

API_KEY = os.getenv("AERO_API_KEY")
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

app = FastAPI(title="Aero-Hydra API")

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == API_KEY:
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate credentials"
    )


# Allow your local frontend to talk to the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For production, replace with your specific domain
    allow_methods=["*"],
    allow_headers=["*"],
)
# Dependency to get the DB session per request
def get_db():
    db = migrate.SessionLocal()
    try:
        yield db
    finally:
        db.close()

DbSession = Annotated[Session, Depends(get_db)]

@app.get("/")
def read_root():
    return {"message": "Welcome to the Aero-Hydra Flight API"}


def _get_aircraft_with_details(db: Session, icao_filter=None):
    """Common logic for querying aircraft, their last telemetry, and airfield names."""
    query = db.query(
        migrate.TrackedAircraft, 
        migrate.Airfield,
        migrate.FlightTelemetry
    ).outerjoin(
        migrate.FlightTelemetry,
        and_(
            migrate.TrackedAircraft.icao24 == migrate.FlightTelemetry.icao24,
            migrate.TrackedAircraft.last_seen == migrate.FlightTelemetry.timestamp
        )
    ).outerjoin(
        migrate.Airfield, 
        migrate.FlightTelemetry.latest_airfield == migrate.Airfield.icao
    )

    if icao_filter is not None:
        query = query.filter(migrate.TrackedAircraft.icao24.in_(icao_filter))

    results = query.all()

    return [
        {
            "icao24": a.icao24, 
            "registration": a.registration, 
            "country": a.country,
            "owner": a.owner,
            "payload_capacity_kg": a.payload_capacity_kg,
            "model": a.aircraft_model,
            "type": a.aircraft_type,
            "sea_landing": a.sea_landing,
            "icon": a.icon_id, 
            "is_full": ft.is_full if ft else None,
            "at_airfield": ft.at_airfield if ft else None,
           
            "last_timestamp": a.last_seen,
            "last_airfield": ft.latest_airfield if ft else "", # The ICAO code (e.g., LSGG)
            "true_track": ft.true_track if ft else None,
            "airfield_name": af.name if af else "Unknown", # The full name
            "last_lat": ft.lat if ft else None,
            "last_lon": ft.lon if ft else None,
            "last_speed_kt": ft.speed_kt if ft else None,
            "last_speed_kph": ft.speed_kph if ft else None,
            "last_baro_alt_ft": ft.baro_altitude_ft if ft else None,
            "last_agl_alt_ft": ft.altitude_agl_ft if ft else None
        } for a, af, ft in results
    ]


@app.get("/aircraft", response_model=List[dict], dependencies=[Security(get_api_key)])
def list_aircraft(db: DbSession):
    return _get_aircraft_with_details(db)


@app.get("/aircraft/active", response_model=List[dict], dependencies=[Security(get_api_key)])
def list_active_aircraft(
    start: int, 
    stop: int, 
    db: DbSession
):
    # 1. Get unique ICAOs within timeframe
    active_icaos = db.query(migrate.TrackedAircraft.icao24).filter(
        migrate.TrackedAircraft.last_seen >= start,
        migrate.TrackedAircraft.last_seen <= stop
    ).all()

    
    icao_list = [i[0] for i in active_icaos]

    # 2. Use helper with the icao filter
    return _get_aircraft_with_details(db, icao_filter=icao_list)
    
@app.get("/telemetry/{icao24}", responses={400: {"description": "icao24 not found"}}, dependencies=[Security(get_api_key)])
def get_telemetry(
    db: DbSession,
    icao24: str, 
    start: Optional[int] = None, 
    stop: Optional[int] = None,
    limit: int = 1000
):
    # Validation: 24-hour check (86400 seconds)
    if start is None and stop is None:
        stop = int(time.time())
        start = stop - 86400

    elif stop is None:
        stop = int(time.time())
        
    if start and stop:
        timespan = stop - start
        if timespan < 0:
            raise HTTPException(status_code=400,                     
                detail="Start timestamp must be before stop timestamp.")
        if timespan > 86400:
            raise HTTPException(status_code=400, 
                detail="Timespan exceeds 24 hours. Please reduce the range for a more precise mission view."
            )
        
    # Query construction
    query = db.query(migrate.FlightTelemetry).filter(
        migrate.FlightTelemetry.icao24 == icao24,
        migrate.FlightTelemetry.timestamp >= start,
        migrate.FlightTelemetry.timestamp <= stop
        )

    points = query.order_by(migrate.FlightTelemetry.timestamp.desc()).limit(limit).all()

    # Create a list of dictionaries with the added altitude in feet
    results = []
    for p in points:
        # Convert the SQLAlchemy model instance to a dictionary
        p_dict = {column.name: getattr(p, column.name) for column in p.__table__.columns}
        
        # Add the calculated feet (1 meter = 3.28084 feet)
        if p_dict.get("baro_altitude") is not None:
            p_dict["baro_altitude_ft"] = round(p_dict["baro_altitude"] * 3.28084)
        else:
            p_dict["baro_altitude_ft"] = None
            
        results.append(p_dict)

    return results

@app.get("/regions-of-interest", dependencies=[Security(get_api_key)]) # Updated to match your frontend fetch URL
def get_rois(
    db: DbSession,
    level: Annotated[Optional[int], Query(ge=1, le=4)] = None,
    type: Annotated[Optional[str], Query(pattern="^(fire|water)$", description="Filter by 'fire' or 'water'")] = None
    ):

    query = db.query(migrate.RegionOfInterest)
    
    # Filter if level is provided
    if level is not None:
        query = query.filter(migrate.RegionOfInterest.level == level)

    # Filter by Type
    if type is not None:
        query = query.filter(migrate.RegionOfInterest.type == type)
        
    rois = query.all()
    
    return [
        {
            "id": r.id,
            "name": r.name,
            "lat": r.lat,
            "lon": r.lon,
            "type": r.type,
            "level": r.level,
            "density": r.density,
            "detected_at": r.detected_at.isoformat() if r.detected_at else None,
            "geometry": r.geometry
        } for r in rois
    ]
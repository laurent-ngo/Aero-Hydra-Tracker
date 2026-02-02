from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional
import migrate # Importing your existing models and SessionLocal

app = FastAPI(title="Aero-Hydra API")


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

@app.get("/")
def read_root():
    return {"message": "Welcome to the Aero-Hydra Flight API"}

@app.get("/aircraft", response_model=List[dict])
def list_aircraft(db: Session = Depends(get_db)):
    # 1. Use a Join to get the Airfield details linked to the aircraft
    # isouter=True ensures we still get the aircraft even if the airfield is NULL
    
    results = db.query(
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
    ).all()

    # 2. Convert to dictionary including the new fields
    return [
        {
            "icao24": a.icao24, 
            "registration": a.registration, 
            "country": a.country,
            "owner": a.owner,
            "payload_capacity_kg": a.payload_capacity_kg,
            "model": a.aircraft_model,
            "type": a.aircraft_type,
           
            "last_timestamp": a.last_seen,
            "last_airfield": ft.latest_airfield if ft else "", # The ICAO code (e.g., LSGG)
            "airfield_name": af.name if af else "Unknown", # The full name
            "last_lat": ft.lat if ft else None,
            "last_lon": ft.lon if ft else None,
            "last_baro_alt_ft": ft.baro_altitude_ft if ft else None,
            "last_agl_alt_ft": ft.altitude_agl_ft if ft else None
            
        } for a, af, ft in results
    ]


@app.get("/aircraft/active", response_model=List[dict])
def list_active_aircraft(start: int, stop: int, db: Session = Depends(get_db)):
    # 1. Get unique ICAOs from telemetry within the timeframe
    active_icaos = db.query(migrate.FlightTelemetry.icao24).filter(
        migrate.FlightTelemetry.timestamp >= start,
        migrate.FlightTelemetry.timestamp <= stop
    ).distinct().all()
    
    icao_list = [i[0] for i in active_icaos]

    # 2. Join TrackedAircraft with Airfield to get the names
    results = db.query(
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
    ).filter(
        migrate.TrackedAircraft.icao24.in_(icao_list)
    ).all()

    return [
        {
            "icao24": a.icao24, 
            "registration": a.registration, 
            "country": a.country,
            "owner": a.owner,
            "payload_capacity_kg": a.payload_capacity_kg,
            "model": a.aircraft_model,
            "type": a.aircraft_type,
           
            "last_timestamp": a.last_seen,
            "last_airfield": ft.latest_airfield if ft else "", # The ICAO code (e.g., LSGG)
            "airfield_name": af.name if af else "Unknown", # The full name
            "last_lat": ft.lat if ft else None,
            "last_lon": ft.lon if ft else None,
            "last_baro_alt_ft": ft.baro_altitude_ft if ft else None,
            "last_agl_alt_ft": ft.altitude_agl_ft if ft else None
        } for a, af, ft in results
    ]
    
@app.get("/telemetry/{icao24}")
def get_telemetry(
    icao24: str, 
    start: Optional[int] = None, 
    stop: Optional[int] = None,
    limit: int = 1000, 
    db: Session = Depends(get_db)
):
    query = db.query(migrate.FlightTelemetry).filter(migrate.FlightTelemetry.icao24 == icao24)

    # Apply date filters if they are provided
    if start:
        query = query.filter(migrate.FlightTelemetry.timestamp >= start)
    if stop:
        query = query.filter(migrate.FlightTelemetry.timestamp <= stop)

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

@app.get("/regions-of-interest") # Updated to match your frontend fetch URL
def get_rois(level: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(migrate.RegionOfInterest)
    
    # Filter if level is provided
    if level is not None:
        query = query.filter(migrate.RegionOfInterest.level == level)
        
    rois = query.all()
    
    return [
        {
            "id": r.id,
            "name": r.name,
            "lat": r.lat,
            "lon": r.lon,
            "level": r.level,
            "density": r.density,
            "detected_at": r.detected_at.isoformat() if r.detected_at else None,
            "geometry": r.geometry
        } for r in rois
    ]
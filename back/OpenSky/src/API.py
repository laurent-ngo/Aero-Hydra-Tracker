from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
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
    aircraft = db.query(migrate.TrackedAircraft).all()
    # Converting SQLAlchemy objects to simple dictionariesc
    return [
        {
            "icao24": a.icao24, 
            "registration": a.registration, 
            "country": a.country,
            "owner": a.owner,
            "payload_capacity_kg": a.payload_capacity_kg,
            "model": a.aircraft_model,
            "type": a.aircraft_type
        } for a in aircraft
    ]

@app.get("/aircraft/active")
def get_active_aircraft(start: int, stop: int, db: Session = Depends(get_db)):
    # We query the TrackedAircraft table (which has registration/model)
    # and join it to Telemetry to see who was active in that window
    active_list = db.query(migrate.TrackedAircraft)\
        .join(migrate.FlightTelemetry, migrate.TrackedAircraft.icao24 == migrate.FlightTelemetry.icao24)\
        .filter(migrate.FlightTelemetry.timestamp >= start)\
        .filter(migrate.FlightTelemetry.timestamp <= stop)\
        .distinct().all()
    
    return [
        {
            "icao24": a.icao24, 
            "registration": a.registration, 
            "country": a.country,
            "owner": a.owner,
            "payload_capacity_kg": a.payload_capacity_kg,
            "model": a.aircraft_model,
            "type": a.aircraft_type
        } for a in active_list
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
    return points

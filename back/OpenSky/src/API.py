from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import migrate # Importing your existing models and SessionLocal

app = FastAPI(title="Aero-Hydra API")

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
    # Converting SQLAlchemy objects to simple dictionaries
    return [
        {
            "icao24": a.icao24, 
            "registration": a.registration, 
            "owner": a.owner,
            "model": a.aircraft_model
        } for a in aircraft
    ]

@app.get("/telemetry/{icao24}")
def get_telemetry(icao24: str, limit: int = 100, db: Session = Depends(get_db)):
    points = db.query(migrate.FlightTelemetry)\
               .filter(migrate.FlightTelemetry.icao24 == icao24)\
               .order_by(migrate.FlightTelemetry.timestamp.desc())\
               .limit(limit).all()
    return points
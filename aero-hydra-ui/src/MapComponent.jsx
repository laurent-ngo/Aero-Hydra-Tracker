import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet'; 
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

function ChangeView({ center }) {
  const map = useMap();
  useEffect(() => {
    if (center) {
      map.flyTo(center, 12, {
        duration: 2.0, // Increase this for a smoother, more "charming" glide
        easeLinearity: 0.25
      });
    }
  }, [center, map]);
  return null;
}

// Icon colors matching your status logic
const COLORS = {
  ground: { fill: "#94a3b8", stroke: "#475569" },   // Grey
  airborne: { fill: "#22c55e", stroke: "#15803d" }, // Green
  full: { fill: "#60a5fa", stroke: "#1d4ed8" },     // Blue
  empty: { fill: "#f97316", stroke: "#c2410c" },    // Orange
};

const createAircraftIcon = (heading = 0, isOnGround = false, payload = false, full = false, aircraftType = "") => {
  let color = COLORS.airborne;
  if (isOnGround) color = COLORS.ground;
  else if (payload) color = full ? COLORS.full : COLORS.empty;

  const planePath = "M21 16V14.5L13 9.5V3.5C13 2.67 12.33 2 11.5 2C10.67 2 10 2.67 10 3.5V9.5L2 14.5V16L10 13.5V19L8 20.5V22L11.5 21L15 22V20.5L13 19V13.5L21 16Z";
  
  const heliPath = "M12 2L11 4.5H5V6.5H11V10.1C9.3 10.4 8 11.9 8 13.5C8 15.5 9.8 17 12 17C14.2 17 16 15.5 16 13.5C16 11.9 14.7 10.4 13 10.1V6.5H19V4.5H13L12 2ZM2 11V13H22V11H2ZM11 18V22H13V18H11Z";
  
  const type = aircraftType?.toLowerCase().trim();
  const selectedPath = (type === 'helicopter') ? heliPath : planePath;

  return L.divIcon({
    html: `
      <div style="transform: rotate(${heading}deg); transition: all 0.3s ease;">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
          <path d="${selectedPath}" 
                fill="${color.fill}" stroke="${color.stroke}" stroke-width="1.5" />
        </svg>
      </div>`,
    className: "bg-transparent",
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
};

const getAltitudeColor = (alt) => {
  if (alt === null || alt <10 ) return '#94a3b8'; // Gray for unknown
  if (alt < 950) return '#f97316';    // Orange: Near Ground/Taxi
  if (alt < 5000) return '#fbce00';   // Yellow: Low altitude/Climb
  if (alt < 13000) return '#22c55e';  // Green: Mid altitude
  if (alt < 200000) return '#3b82f6';  // Blue: High altitude
  return '#a855f7';                     // Purple: Very high/Cruise
};

const MapComponent = ({ aircraft = [], timeRangeSeconds = 3600, center }) => {
  const [telemetryPaths, setTelemetryPaths] = useState({});
  const position = [43.758662, 4.416307];

  useEffect(() => {
  const fetchPaths = async () => {
    const paths = {};
    // Calculate the 24h window (matching your backend limit)
    const stop = Math.floor(Date.now() / 1000);
    const start = stop - timeRangeSeconds;

    await Promise.all(aircraft.map(async (ac) => {
      try {
        // Explicitly pass start/stop so the backend has a valid range
        const response = await fetch(`http://localhost:8000/telemetry/${ac.icao24}?start=${start}&stop=${stop}`, {
            headers: {
                'X-API-Key': import.meta.env.VITE_AERO_API_KEY
            }
        });
        const data = await response.json();

        if (Array.isArray(data) && data.length > 0) {
          paths[ac.icao24] = data
            .filter(p => p.lat !== null && p.lon !== null)
            .map(p => ({
              lat: Number(p.lat),
              lon: Number(p.lon),
              alt: Number(p.altitude_agl_ft) 
            }));
        }
      } catch (error) {
        console.error(`Telemetry fetch failed for ${ac.icao24}:`, error);
      }
    }));
    setTelemetryPaths(paths);
  };

  if (aircraft.length > 0) {
    fetchPaths();
  }
},[aircraft, timeRangeSeconds]);

  return (
    <MapContainer 
      center={position} 
      zoom={10} 
      style={{ height: '100%', width: '100%' }} 
      zoomControl={false}
    >
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

        eventHandlers={{
          tileloadstart: (e) => {
            e.tile.setAttribute('referrerpolicy', 'no-referrer');
          }
        }}
      />
      
      {center && <ChangeView center={center} />}
      {aircraft
        .filter(ac => ac.last_lat !== null && ac.last_lon !== null)
        .map((ac) => {
          const isOnGround = ac.at_airfield === true;
          const pathCoords = telemetryPaths[ac.icao24] || [];

          return (
            <React.Fragment key={ac.icao24}>
              {pathCoords && pathCoords.length > 1 && pathCoords.map((point, index) => {
                if (index === 0) return null;
                  
                const prevPoint = pathCoords[index - 1];

                // 1. Diplomatic Safety Check: Validate every single coordinate
                const isValidSegment = 
                prevPoint && typeof prevPoint.lat === 'number' && typeof prevPoint.lon === 'number' &&
                point && typeof point.lat === 'number' && typeof point.lon === 'number';

                if (!isValidSegment) return null;

                // 2. Strict Array Construction: Ensure it's exactly [[lat, lon], [lat, lon]]
                const segmentPositions = [
                  [prevPoint.lat, prevPoint.lon],
                  [point.lat, point.lon]
                ];

                if (index === 1) console.log(`Drawing path for ${ac.icao24}:`, point);

                return (
                  <Polyline
                    key={`${ac.icao24}-seg-${index}`}
                    // Access .lat and .lon from the objects
                    positions={[
                      [prevPoint.lat, prevPoint.lon],
                      [point.lat, point.lon]
                    ]}
                    pathOptions={{
                      color: getAltitudeColor(point.alt),
                      weight: 4,
                      opacity: 1,
                      lineCap: 'round'
                    }}
                  />
                );
              })}
              {/* 2. Draw the Aircraft Marker */}
              <Marker 
                position={[ac.last_lat, ac.last_lon]} 
                icon={createAircraftIcon(
                  ac.true_track || 0, 
                  ac.at_airfield, 
                  ac.payload_capacity_kg > 0,
                  ac.is_full,
                  ac.type
                )}
              >
                <Popup>
                  <div className="text-slate-900 font-mono p-1 min-w-[160px]">
                    {/* Header: Reg and Model */}
                    <div className="mb-2 border-b border-slate-100 pb-1">
                      <p className="font-bold text-lg text-blue-700 leading-none mb-1">
                        {ac.registration || "N/A"}
                      </p>
                      <p className="text-[11px] text-slate-500 font-sans uppercase font-bold tracking-tight">
                        {ac.model || "Unknown Model"}
                      </p>
                    </div>

                    {/* Instruments: Altitude and Speed */}
                    <div className="grid grid-cols-2 gap-2 mb-2">
                      <div className="flex flex-col">
                        <span className="text-[9px] uppercase text-slate-400 font-sans font-bold">Altitude</span>
                        <span className="text-sm font-bold">
                          {ac.last_baro_alt_ft ? `${Math.round(ac.last_baro_alt_ft)} ft` : '---'}
                        </span>
                      </div>
                    </div>
                  </div>
                </Popup>
              </Marker>
            </React.Fragment>
          );
        })}
    </MapContainer>
  );
};

export default MapComponent;
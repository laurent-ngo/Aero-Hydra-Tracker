import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet'; 
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { Polygon } from 'react-leaflet';
import { THEME } from './theme';
import { Header, Label, Value } from './components/Typography';

const getTimeAgo = (timestamp) => {
  if (!timestamp) return "Unknown";
  
  const lastSeen = new Date(timestamp * 1000); 
  const now = new Date();
  const secondsAgo = Math.floor((now - lastSeen) / 1000);

  if (secondsAgo < 60) return `${secondsAgo}s ago`;
  
  const minutes = Math.floor(secondsAgo / 60);
  if (minutes < 60) {
    const remainingSeconds = secondsAgo % 60;
    return `${minutes}m ${remainingSeconds}s ago`;
  }

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;

  if (hours < 24) {
    return `${hours}h ${remainingMinutes}m ago`;
  }

  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;

  if (days < 7) {
    return `${days}d ${remainingHours}h ago`
  }
  return "+7days ago";
};

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

const createAircraftIcon = (heading = 0, isOnGround = false, payload = false, full = false, iconId = 1) => {

  const ICON_SIZE = 72;
  const iconsPerRow = 8;

  const offsetX = -(iconId%iconsPerRow) * ICON_SIZE;
  const offsetY = -Math.floor(iconId / iconsPerRow)* ICON_SIZE;

  //console.log(`[Sprite Debug] ID: ${iconId} | Offset: ${offsetX}px, ${offsetY}px`);

  let color = COLORS.airborne;
  if (isOnGround) color = COLORS.ground;
  else if (payload) color = full ? COLORS.full : COLORS.empty;

  return L.divIcon({
    html: `
    <div style="
      width: ${ICON_SIZE}px; 
      height: ${ICON_SIZE}px; 
      transform: rotate(${heading}deg);
      display: flex;
      justify-content: center;
      align-items: center;
      filter: drop-shadow(1px 0px 0px black) 
              drop-shadow(-1px 0px 0px black) 
              drop-shadow(0px 1px 0px black) 
              drop-shadow(0px -1px 0px black);
    ">
      <div style="
        width: ${ICON_SIZE}px; 
        height: ${ICON_SIZE}px; 
        background-color: ${color.fill}; 
        -webkit-mask-image: url('../img/sprites.png');
        mask-image: url('../img/sprites.png');
        -webkit-mask-position: ${offsetX}px ${offsetY}px;
        mask-position: ${offsetX}px ${offsetY}px;
        -webkit-mask-repeat: no-repeat;
        transform: scale(0.5); 
      "></div>
    </div>`,
    className: "bg-transparent",
    iconSize: [20, 20],
    iconAnchor: [36, 36],
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

const MapComponent = ({ aircraft = [], rois = [], timeRangeSeconds = 3600, center }) => {
  const [telemetryPaths, setTelemetryPaths] = useState({});
  const position = [43.758662, 4.416307];

  // Styling logic for the ROI level 2
  const roiStyle = {
    color: '#FF0000', 
    weight: 5, 
    fillOpacity: 0.15,
    fillColor: '#FF0000',
    zIndex: 9999 // Force it to the top
  };
  

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

      {rois.map((roi) => {
        let finalCoords = [];

        // 1. Parse the string into a real Array
        try {
          if (typeof roi.geometry === 'string') {
            finalCoords = JSON.parse(roi.geometry);
          } else {
            finalCoords = roi.geometry;
          }
        } catch (e) {
          console.error(`Parsing error for ROI ${roi.id}:`, e);
          return null;
        }

        // 2. Safety check now works because finalCoords is a real Array
        if (!finalCoords || !Array.isArray(finalCoords) || finalCoords.length === 0) {
          return null;
        }

        // 3. Render the Polygon
        return (
          <Polygon 
            key={`roi-${roi.id}`} 
            positions={finalCoords} 
            pathOptions={roiStyle}
          >
            <Popup>
              <div className="text-slate-900 font-mono p-1">
                <Header>{roi.name}</Header>
                <div className="mt-2">
                  <Label>Level</Label>
                  <Value>{roi.level}</Value>
                  <Label>Type</Label>
                  <Value>{roi.type}</Value>
                </div>
              </div>
            </Popup>
          </Polygon>
        );
      })}

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
                  ac.icon
                )}
              >
                <Popup>
                  <div className="text-slate-900 font-mono p-1 min-w-[160px]">
                    {/* Header: Reg and Model */}
                    <div className="mb-2 border-b border-slate-100 pb-1">
                      <Header>
                        {ac.registration || "N/A"}
                      </Header>
                    </div>
                    <div className="mb-2 border-b border-slate-100 pb-1">
                      <Label>
                        {ac.model || "Unknown Model"}
                      </Label>
                    </div>

                    {/* Instruments: Altitude and Speed */}
                    <div className="grid grid-cols-2 gap-2 mb-2">
                      <div className="flex flex-col">
                        <Label>Baro Altitude</Label>
                          <Value>{ac.last_baro_alt_ft ? `${Math.round(ac.last_baro_alt_ft)} ft` : '---'}</Value>
                      </div>
                      <div className="flex flex-col">
                        <Label>AGL Altitude</Label>
                          <Value>{ac.last_agl_alt_ft ? `${Math.round(ac.last_agl_alt_ft)} ft` : '---'}</Value>
                      </div>
                    </div>

                    {/* Footer: Last Seen Status */}
                    <div className="pt-1 border-t border-slate-100 flex justify-between items-center">
                      <Label>Last seen</Label>
                      <Value> {getTimeAgo(ac.last_timestamp)}</Value>
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
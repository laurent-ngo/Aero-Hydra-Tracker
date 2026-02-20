import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet'; 
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { Polygon } from 'react-leaflet';
import { THEME, AIRCRAFT_COLORS, ROI_STYLE, getAltitudeColor } from './theme';
import { Header, Label, Value } from './components/Typography';


const projectPosition = (lat, lon, track, speedKph, timestamp, alt) => {


  // Check for missing data
  if (!lat || !lon) return null;
  if (track === undefined || track === null) return null;
  if (!speedKph || speedKph < 5) return null; // Ignore stationary/slow aircraft
  if (!timestamp) return null;
  if (!alt) return null;
  
  if (alt < 1000) return [lat, lon];

  const now = Math.floor(Date.now() / 1000);
  const diffSeconds = now - timestamp;
  
  // If your timestamp is in milliseconds, diffSeconds will be a huge negative number
  // or a massive positive number. Let's fix that:

  if (diffSeconds > 2400) return null;

  const actualDiff = Math.min(1200, Math.abs(diffSeconds) > 1000000 ? (Date.now() - timestamp) / 1000 : diffSeconds);

  if (actualDiff <= 0) return null;

  // Simple projection math
  const distanceKm = (speedKph * actualDiff) / 3600;
  const latChange = (distanceKm * Math.cos(track * Math.PI / 180)) / 111.32;
  const lonChange = (distanceKm * Math.sin(track * Math.PI / 180)) / 
                    (111.32 * Math.cos(lat * Math.PI / 180));

  return [lat + latChange, lon + lonChange];
};

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

const createAircraftIcon = (heading = 0, isOnGround = false, payload = false, full = false, iconId = 1) => {

  const ICON_SIZE = 72;
  const iconsPerRow = 8;

  const offsetX = -(iconId%iconsPerRow) * ICON_SIZE;
  const offsetY = -Math.floor(iconId / iconsPerRow)* ICON_SIZE;

  //console.log(`[Sprite Debug] ID: ${iconId} | Offset: ${offsetX}px, ${offsetY}px`);

  let color = AIRCRAFT_COLORS.airborne;
  if (isOnGround) color = AIRCRAFT_COLORS.ground;
  else if (payload) color = full ? AIRCRAFT_COLORS.full : AIRCRAFT_COLORS.empty;

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


const MapComponent = ({ aircraft = [], rois = [], timeRangeSeconds = 3600, center, mode = 'dark' }) => {
  const [telemetryPaths, setTelemetryPaths] = useState({});
  const position = [43.758662, 4.416307];

  const mapConfig = THEME.modes[mode].map;

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
        key={mode} 
        url={mapConfig.url}
        attribution={mapConfig.attribution}
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
            pathOptions={ROI_STYLE[roi.type] || ROI_STYLE.fire}
          >
            <Popup>
              <div className="font-mono min-w-[140px]">
                <Header mode={mode}>{roi.name}</Header>
                <div className="mt-2">
                  <Label mode={mode}>Level</Label>
                  <Value mode={mode}>{roi.level}</Value>
                  <Label mode={mode}>Type</Label>
                  <Value mode={mode}>{roi.type}</Value>
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
          
          const projectedPos = projectPosition(
            ac.last_lat, 
            ac.last_lon, 
            ac.true_track, 
            ac.last_speed_kph, 
            ac.last_timestamp,
            ac.last_agl_alt_ft,
          );

          //console.log(`Projecting ${ac.registration}:`, ac.last_lat, ac.last_lon, ac.true_track, ac.last_speed_kph, ac.last_timestamp, projectedPos);

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
                      color: getAltitudeColor(point.alt, mode),
                      weight: 8,
                      opacity: 5,
                      lineCap: 'round'
                    }}
                  />
                );
              })}
              
              {/* The New Projected Track (Dashed line) */}
              {projectedPos && (
                <Polyline
                  positions={[[ac.last_lat, ac.last_lon], projectedPos]}
                  pathOptions={{
                    color: getAltitudeColor(ac.last_agl_alt_ft, mode),
                    weight: 8,
                    dashArray: '5, 10',
                    opacity: 0.8,
                  }}
                />
              )}

              {/* 2. Draw the Aircraft Marker */}
              <Marker 
                position={projectedPos ? projectedPos : [ac.last_lat, ac.last_lon]}
                icon={createAircraftIcon(
                  ac.true_track || 0, 
                  ac.at_airfield, 
                  ac.payload_capacity_kg > 0,
                  ac.is_full,
                  ac.icon
                )}
              >
                <Popup>
                  <div className="font-mono min-w-[140px]">
                    {/* Header: Reg and Model */}
                    <div className="mb-2 border-b border-slate-100 pb-1">
                      <Header mode={mode}>{ac.registration || "N/A"}</Header>
                    </div>
                    <div className="mb-2 border-b border-slate-100 pb-1">
                      <Label mode={mode}>{ac.model || "Unknown Model"}</Label>
                    </div>

                    {/* Instruments: Altitude and Speed */}
                    <div className="grid grid-cols-2 gap-2 mb-2">
                      <div className="flex flex-col">
                        <Label mode={mode}>Baro Altitude</Label>
                          <Value mode={mode}>{ac.last_baro_alt_ft ? `${Math.round(ac.last_baro_alt_ft)} ft` : '---'}</Value>
                      </div>
                      <div className="flex flex-col">
                        <Label mode={mode}>AGL Altitude</Label>
                          <Value mode={mode}>{ac.last_agl_alt_ft ? `${Math.round(ac.last_agl_alt_ft)} ft` : '---'}</Value>
                      </div>
                    </div>

                    {/* Footer: Last Seen Status */}
                    <div className="pt-1 border-t border-slate-100 flex justify-between items-center">
                      <Label mode={mode}>Last seen</Label>
                      <Value mode={mode}> {getTimeAgo(ac.last_timestamp)}</Value>
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
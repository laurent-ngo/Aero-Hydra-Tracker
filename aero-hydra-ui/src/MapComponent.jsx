import React from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

// Fix for missing marker icons in Vite
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

const DefaultIcon = L.icon({
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});
L.Marker.prototype.options.icon = DefaultIcon;

const COLORS = {
  airborne: { fill: "#60a5fa", stroke: "#1d4ed8" }, // Blue
  ground: { fill: "#fb923c", stroke: "#c2410c" }    // Orange
};

const createAircraftIcon = (heading = 0, isOnGround = false) => {
  const color = isOnGround ? COLORS.ground : COLORS.airborne;
  
  return L.divIcon({
    html: `
      <div style="transform: rotate(${heading}deg); transition: all 0.5s ease-in-out;">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M21 16V14.5L13 9.5V3.5C13 2.67 12.33 2 11.5 2C10.67 2 10 2.67 10 3.5V9.5L2 14.5V16L10 13.5V19L8 20.5V22L11.5 21L15 22V20.5L13 19V13.5L21 16Z" 
                fill="${color.fill}" 
                stroke="${color.stroke}" 
                stroke-width="1.5" />
        </svg>
      </div>`,
    className: "bg-transparent",
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
};

const MapComponent = ({ aircraft = [] }) => {
  // Center of Switzerland/Nyon area as default
  const position = [46.3833, 6.2348];

  return (
    <MapContainer 
      center={position} 
      zoom={11} 
      style={{ height: '100%', width: '100%' }}
      zoomControl={false}
    >
      {/* Dark Mode Map Tiles */}
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />
      
      {aircraft
        .filter(ac => ac.last_lat !== null && ac.last_lon !== null)
        .map((ac) => {
            // Explicit ground check based on your API field
            const isOnGround = ac.at_airfield === true;

            return (
            <Marker 
                key={ac.icao24} 
                position={[ac.last_lat, ac.last_lon]}
                icon={createAircraftIcon(ac.true_track || 0, isOnGround)}
            >
                <Popup>
                <div className="text-slate-900 font-sans p-1">
                    <p className="font-bold border-b border-slate-200 pb-1 mb-1">{ac.registration}</p>
                    <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${isOnGround ? 'bg-orange-500' : 'bg-blue-500'}`}></div>
                    <span className="text-xs font-bold uppercase">
                        {isOnGround ? `On Ground - ${ac.airfield_name || 'Airport'}` : "Airborne"}
                    </span>
                    </div>
                    {!isOnGround && <p className="text-[10px] mt-1 text-slate-500">Alt: {ac.last_baro_alt_ft} ft</p>}
                </div>
                </Popup>
            </Marker>
            );
        })}
    </MapContainer>
  );
};

export default MapComponent;
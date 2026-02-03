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

const createAircraftIcon = (heading = 0) => {
  return L.divIcon({
    html: `
      <div style="transform: rotate(${heading}deg); transition: transform 0.5s ease-in-out;">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M21 16V14.5L13 9.5V3.5C13 2.67 12.33 2 11.5 2C10.67 2 10 2.67 10 3.5V9.5L2 14.5V16L10 13.5V19L8 20.5V22L11.5 21L15 22V20.5L13 19V13.5L21 16Z" 
                fill="#60a5fa" 
                stroke="#1d4ed8" 
                stroke-width="1" />
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
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        attribution='&copy; OpenStreetMap contributors &copy; CARTO'
      />
      
      {aircraft
        .filter(ac => ac.last_lat !== null && ac.last_lon !== null)
        .map((ac) => (
            <Marker 
            key={ac.icao24} 
            position={[ac.last_lat, ac.last_lon]}
            icon={createAircraftIcon(ac.true_track || 0)} // Pass the heading here
            >
            <Popup>
                <div className="text-slate-900 font-sans">
                <p className="font-bold">{ac.registration}</p>
                <p className="text-xs">Heading: {ac.true_track}°</p>
                </div>
            </Popup>
            </Marker>
        ))}
    </MapContainer>
  );
};

export default MapComponent;
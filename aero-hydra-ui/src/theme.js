export const THEME = {
  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
  colors: {
    textPrimary: "#1e293b",
    textSecondary: "#64748b",
    accent: "#1d4ed8",
    border: "#f1f5f9",
    background: "#ffffff",
    success: "#16a34a",
    danger: "#ef4444"
  },
  fontSize: {
    label: "9px",
    value: "13px",
    header: "16px"
  }
};


export const TRACK_COLORS = {
  ground:   "#475569", // Grey
  airborne: "#15803d", // Green
  full:     "#1d4ed8", // Blue
  empty:    "#c2410c", // Orange
};

export const AIRCRAFT_COLORS = {
  ground: { fill: "#94a3b8"},   // Grey
  airborne: { fill: "#22c55e"}, // Green
  full: { fill: "#60a5fa"},     // Blue
  empty: { fill: "#f97316"},    // Orange
};

export const ROI_STYLE = {
  color: '#ff9100', 
  weight: 5, 
  fillOpacity: 0.25,
  fillColor: '#aa7400',
  zIndex: 9999 // Force it to the top
};

export const getAltitudeColor = (alt) => {
  if (alt === null || alt <1 ) return '#94a3b8'; // Gray for unknown
  if (alt <100 ) return '#ff0000'; 
  if (alt < 950) return '#f97316';    // Orange: Near Ground/Taxi
  if (alt < 5000) return '#fbce00';   // Yellow: Low altitude/Climb
  if (alt < 13000) return '#22c55e';  // Green: Mid altitude
  if (alt < 200000) return '#3b82f6';  // Blue: High altitude
  return '#a855f7';                     // Purple: Very high/Cruise
};


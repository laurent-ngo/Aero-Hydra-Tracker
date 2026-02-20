export const THEME = {
  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
  // Split colors into modes
  modes: {
    light: {
      textPrimary: "#1e293b",   
      textSecondary: "#64748b", 
      accent: "#1d4ed8",        
      border: "#e2e8f0",        
      background: "#ffffff",
      sidebar: "#f8fafc",       
      success: "#16a34a",
      danger: "#ef4444",
      map: {
        url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      }
    },
    dark: {
      textPrimary: "#f1f5f9",   
      textSecondary: "#94a3b8", 
      accent: "#60a5fa",        
      border: "#1e293b",        
      background: "#020617",    
      sidebar: "#0f172a",       
      success: "#22c55e",
      danger: "#f87171",
      map: {
        url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
      }
    }
  },
  fontSize: {
    label: "9px",
    value: "13px",
    header: "16px"
  }
};

// Keep your existing TRACK_COLORS, AIRCRAFT_COLORS, ROI_STYLE as is
// or move them into the modes if you want them to change too.


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
  fire: {
    color: '#ff9100', 
    weight: 5, 
    fillOpacity: 0.25,
    fillColor: '#aa7400',
    zIndex: 9999 // Force it to the top
  },
  training:{
    color: '#16a10a', 
    weight: 5, 
    fillOpacity: 0.25,
    fillColor: '#00aa1c',
    zIndex: 9999 // Force it to the top
  }
};


const ALTITUDE_PALETTE = {
  light: {
    unknown: '#94a3b8',
    ground:  '#ff0000',
    taxi:    '#f97316',
    low:     '#fbce00',
    mid:     '#22c55e',
    high:    '#3b82f6',
    cruise:  '#a855f7'
  },
  dark: {
    unknown: '#64748b', // Deeper gray
    ground:  '#b60d0d', // Stronger red
    taxi:    '#a04819', // Deep orange
    low:     '#a06f06', // Darker yellow/gold (better contrast on white)
    mid:     '#107736', // Forest green
    high:    '#1d4db4', // Royal blue
    cruise:  '#6c26ad'  // Deep purple
  }
};

export const getAltitudeColor = (alt, mode = 'dark') => {
  const colors = ALTITUDE_PALETTE[mode] || ALTITUDE_PALETTE.dark;

  if (alt === null || alt < 1) return colors.unknown;
  if (alt < 100)               return colors.ground; 
  if (alt < 950)               return colors.taxi;
  if (alt < 5000)              return colors.low;
  if (alt < 13000)             return colors.mid;
  if (alt < 200000)            return colors.high;
  return colors.cruise;
};


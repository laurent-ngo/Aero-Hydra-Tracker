import React, { useState, useEffect, useCallback } from 'react';
import { Plane, Clock, ChevronLeft, ChevronRight } from 'lucide-react'; // Added Chevrons
import MapComponent from './MapComponent';

const TIME_OPTIONS = [
  { label: '5m', seconds: 300 },
  { label: '15m', seconds: 900 },
  { label: '30m', seconds: 1800 },
  { label: '1h', seconds: 3600 },
  { label: '2h', seconds: 7200 },
  { label: '4h', seconds: 14400 },
  { label: '8h', seconds: 28800 },
  { label: '12h', seconds: 43200 },
  { label: '24h', seconds: 86400 },
];

const COLORS = {
  ground:   "#475569", // Grey
  airborne: "#15803d", // Green
  full:     "#1d4ed8", // Blue
  empty:    "#c2410c", // Orange
};

// At the top of App.jsx
if (!import.meta.env.VITE_AERO_API_KEY) {
    throw new Error(
        "CRITICAL: VITE_AERO_API_KEY is missing from environment variables. " +
        "Check your .env.local file and restart the dev server."
    );
}


function App() {
  const [aircraft, setAircraft] = useState([]);
  const [showAll, setShowAll] = useState(false); // New: Toggle State
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [isResizing, setIsResizing] = useState(false);
  const [timeIndex, setTimeIndex] = useState(3);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [mapCenter, setMapCenter] = useState([43.758662, 4.416307]);

  const selectedTime = TIME_OPTIONS[timeIndex];

  const handleAircraftClick = (ac) => {
    if (ac.last_lat && ac.last_lon) {
      console.log(`Centering on ${ac.registration}:`, [ac.last_lat, ac.last_lon]);
      setMapCenter([Number(ac.last_lat), Number(ac.last_lon)]);
    }
  };
  
  const getAircraftColor = (ac) => {
    if (ac.at_airfield) return COLORS.ground;
    if (ac.payload_capacity_kg > 0) {
      return ac.is_full ? COLORS.full : COLORS.empty;
    }
    return COLORS.airborne;
  };

  // --- Resizing Logic ---
  const startResizing = useCallback(() => setIsResizing(true), []);
  const stopResizing = useCallback(() => setIsResizing(false), []);
  const resize = useCallback((e) => {
    if (isResizing && !isCollapsed) {
      const newWidth = Math.min(Math.max(200, e.clientX), 600);
      setSidebarWidth(newWidth);
    }
  }, [isResizing, isCollapsed]);

  useEffect(() => {
    globalThis.addEventListener("pointermove", resize);
    globalThis.addEventListener("pointerup", stopResizing);
    return () => {
      globalThis.removeEventListener("pointermove", resize);
      globalThis.removeEventListener("pointerup", stopResizing);
    };
  }, [resize, stopResizing]);

  // --- Data Fetching ---
  useEffect(() => {
    const fetchData = async () => {
      try {
        const stop = Math.floor(Date.now() / 1000);
        const start = stop - selectedTime.seconds;
        
        // Toggle between "Active" and "All" endpoints
        const url = showAll 
          ? `http://localhost:8000/aircraft` 
          : `http://localhost:8000/aircraft/active?start=${start}&stop=${stop}`;

        const response = await fetch(url, {
            headers: { 'X-API-Key': import.meta.env.VITE_AERO_API_KEY }
        }); 
        const data = await response.json();
        setAircraft(Array.isArray(data) ? data : (data ? [data] : []));
      } catch (error) {
        console.error("API Error:", error);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [selectedTime, showAll]); // Re-run when toggle or time changes

  return (
    <div className="flex h-screen w-screen bg-slate-950 overflow-hidden select-none">
      <aside 
        style={{ width: isCollapsed ? '64px' : `${sidebarWidth}px` }} 
        className="h-full bg-slate-900 border-r border-slate-800 flex flex-col z-[1001] shrink-0 transition-all duration-300 ease-in-out"
      >
        <div className="p-4 border-b border-slate-800 flex items-center justify-between overflow-hidden">
          {!isCollapsed && <h1 className="text-xl font-bold text-blue-400">AERO-HYDRA</h1>}
          <button onClick={() => setIsCollapsed(!isCollapsed)} className="p-1 hover:bg-slate-800 rounded text-slate-400">
            {isCollapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
          </button>
        </div>

        {/* Time Slider & and toggle */}
        {!isCollapsed && (
          <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
            <span className="text-[10px] uppercase font-bold text-slate-500">View Mode</span>
            <button 
              onClick={() => setShowAll(!showAll)}
              className={`px-3 py-1 rounded-full text-[10px] font-bold transition-all border ${
                showAll ? 'bg-blue-500/20 border-blue-500 text-blue-400' : 'bg-slate-800 border-slate-700 text-slate-400'
              }`}
            >
              {showAll ? 'ALL KNOWN' : 'ACTIVE ONLY'}
            </button>
          </div>
        )}

        {!isCollapsed && (
           <div className="p-4 border-b border-slate-800 space-y-4">
              <div className="space-y-2 bg-slate-800/40 p-3 rounded-lg border border-slate-700/50">
                <div className="flex justify-between items-center text-[10px] uppercase tracking-wider font-bold text-slate-500">
                  <div className="flex items-center gap-1">
                    <Clock size={12} /> <span>History Range</span>
                  </div>
                  <span className="text-blue-400 font-mono">{selectedTime.label}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max={TIME_OPTIONS.length - 1}
                  value={timeIndex}
                  onChange={(e) => setTimeIndex(Number.parseInt(e.target.value))}
                  className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
                />
              </div>
           </div>
        )}

        {/* Aircraft List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2 overflow-x-hidden">
          {aircraft.map((ac) => {
            const statusColor = getAircraftColor(ac);
            return (
              <div 
                key={ac.icao24} 
                // 3. ADD THIS ONCLICK:
                onClick={() => handleAircraftClick(ac)}
                className={`rounded-lg border bg-slate-800/50 hover:bg-slate-800/80 transition-all cursor-pointer group ${isCollapsed ? 'p-2 flex justify-center' : 'p-3'}`}
                style={{ borderColor: `${statusColor}33` }}
              >
                <div className="flex items-start" style={{ display: 'flex', alignItems: 'flex-start' }}>
                    {/* ... icon and text logic ... */}
                    <div className="shrink-0" style={{ width: '40px', paddingRight: '15px', display: 'flex', justifyContent: 'center', marginTop: '4px' }}>
                         <Plane size={18} style={{ color: statusColor, transform: 'rotate(45deg)', flexShrink: 0 }} />
                    </div>
                    {!isCollapsed && (
                        <div className="flex-1 min-w-0">
                            {/* ... reg and airfield ... */}
                            <div className="flex justify-between items-baseline w-full">
                                <span className="font-mono font-bold text-slate-100 truncate max-w-[40%]">{ac.registration || "N/A"}</span>
                                <div className="flex items-center gap-2 min-w-0 max-w-[55%]">
                                    <span className="text-slate-500 truncate text-right w-full text-[9px] italic">
                                        {ac.airfield_name || (ac.at_airfield ? "On Ground" : "In Transit")}
                                    </span>
                                    <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: statusColor, boxShadow: `0 0 6px ${statusColor}` }} />
                                </div>
                            </div>
                            <p className="text-[10px] text-blue-400 font-bold uppercase tracking-tight truncate mt-0.5">{ac.model || "Unknown Model"}</p>
                        </div>
                    )}
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      {/* Resizer Handle (Hidden when collapsed) */}
      {!isCollapsed && (
        <div 
          onPointerDown={startResizing} // Changed from onMouseDown
          className="w-1 cursor-col-resize bg-slate-800 hover:bg-blue-500 transition-colors z-[1002]" 
        />
      )}

      <main className="flex-1 relative h-full bg-slate-900">
        {/* 4. PASS THE CENTER PROP: This tells MapComponent where to fly */}
        <MapComponent 
            aircraft={aircraft} 
            timeRangeSeconds={selectedTime.seconds} 
            center={mapCenter} 
        />
      </main>
    </div>
  );
}

export default App;
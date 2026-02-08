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

function App() {
  const [aircraft, setAircraft] = useState([]);
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [isResizing, setIsResizing] = useState(false);
  const [timeIndex, setTimeIndex] = useState(3);
  const [isCollapsed, setIsCollapsed] = useState(false); // New state

  const selectedTime = TIME_OPTIONS[timeIndex];

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
    globalThis.addEventListener("mousemove", resize);
    globalThis.addEventListener("mouseup", stopResizing);
    return () => {
      globalThis.removeEventListener("mousemove", resize);
      globalThis.removeEventListener("mouseup", stopResizing);
    };
  }, [resize, stopResizing]);

  // --- Data Fetching (Updated for Time Selection) ---
  useEffect(() => {
    const fetchData = async () => {
      try {
        const stop = Math.floor(Date.now() / 1000);
        const start = stop - selectedTime.seconds;
        
        // Using your specific endpoint for active aircraft in a time range
        const response = await fetch(`http://localhost:8000/aircraft/active?start=${start}&stop=${stop}`);
        const data = await response.json();
        setAircraft(Array.isArray(data) ? data : (data ? [data] : []));
      } catch (error) {
        console.error("API Error:", error);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [selectedTime]); // Re-run when time selection changes

  return (
    <div className="flex h-screen w-screen bg-slate-950 overflow-hidden select-none">
      
      <aside 
        style={{ width: isCollapsed ? '64px' : `${sidebarWidth}px` }} 
        className="h-full bg-slate-900 border-r border-slate-800 flex flex-col z-[1001] shrink-0 transition-all duration-300 ease-in-out"
      >
        {/* Header & Toggle */}
        <div className="p-4 border-b border-slate-800 flex items-center justify-between overflow-hidden whitespace-nowrap">
          {!isCollapsed && <h1 className="text-xl font-bold text-blue-400">AERO-HYDRA</h1>}
          <button 
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="p-1 hover:bg-slate-800 rounded text-slate-400"
          >
            {isCollapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
          </button>
        </div>

        {/* Time Slider (Hidden when collapsed) */}
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
                className={`rounded-lg border bg-slate-800/50 transition-all cursor-pointer ${isCollapsed ? 'p-2 flex justify-center' : 'p-3'}`}
                style={{ borderColor: `${statusColor}33` }}
              >
                <Plane 
                  size={18} 
                  style={{ color: statusColor, transform: 'rotate(45deg)' }} 
                />
                {!isCollapsed && (
                  <div className="ml-3 flex-1">
                    <span className="font-mono font-bold text-slate-100">{ac.registration}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </aside>

      {/* Resizer Handle (Hidden when collapsed) */}
      {!isCollapsed && (
        <div
          onMouseDown={startResizing}
          className="w-1 cursor-col-resize bg-slate-800 hover:bg-blue-500 transition-colors z-[1002]"
        />
      )}

      <main className="flex-1 relative h-full bg-slate-900">
        <MapComponent aircraft={aircraft} timeRangeSeconds={selectedTime.seconds} />
      </main>
    </div>
  );
}

export default App;
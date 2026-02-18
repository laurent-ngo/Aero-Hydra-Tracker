import React, { useState, useEffect, useCallback } from 'react';
import { Plane, Clock, ChevronLeft, ChevronRight, Target, Sun, Moon } from 'lucide-react'; // Added Chevrons
import MapComponent from './MapComponent';

import { TRACK_COLORS, THEME } from './theme';
import { Header, Label, Value } from './components/Typography';


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

// At the top of App.jsx
if (!import.meta.env.VITE_AERO_API_KEY) {
    throw new Error(
        "CRITICAL: VITE_AERO_API_KEY is missing from environment variables. " +
        "Check your .env.local file and restart the dev server."
    );
}


function App() {
  const [aircraft, setAircraft] = useState([]);
  const [rois, setRois] = useState([]);
  const [showAll, setShowAll] = useState(false); // New: Toggle State
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [isResizing, setIsResizing] = useState(false);
  const [timeIndex, setTimeIndex] = useState(3);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [mapCenter, setMapCenter] = useState([43.758662, 4.416307]);
  const [isDarkMode, setIsDarkMode] = useState(
    window.matchMedia('(prefers-color-scheme: dark)').matches
  );
  
  const currentMode = isDarkMode ? 'dark' : 'light';

  const toggleTheme = () => {
    setIsDarkMode(prev => !prev);
  };

  const selectedTime = TIME_OPTIONS[timeIndex];

  const handleAircraftClick = (ac) => {
    if (ac.last_lat && ac.last_lon) {
      console.log(`Centering on ${ac.registration}:`, [ac.last_lat, ac.last_lon]);
      setMapCenter([Number(ac.last_lat), Number(ac.last_lon)]);
    }
  };
  
  const getAircraftColor = (ac) => {
    if (ac.airfield_name === 'Unknown') return TRACK_COLORS.ground
    if (ac.at_airfield) return TRACK_COLORS.ground;
    if (ac.payload_capacity_kg > 0) {
      return ac.is_full ? TRACK_COLORS.full : TRACK_COLORS.empty;
    }
    return TRACK_COLORS.airborne;
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
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    
    // Listener for real-time changes
    const handleChange = (e) => setIsDarkMode(e.matches);
    
    query.addEventListener('change', handleChange);
    return () => query.removeEventListener('change', handleChange);
  }, []);

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

        const headers = { 'X-API-Key': import.meta.env.VITE_AERO_API_KEY };
        
       // Fetch Aircraft
        const acUrl = showAll 
          ? `http://localhost:8000/aircraft` 
          : `http://localhost:8000/aircraft/active?start=${start}&stop=${stop}`;
        const acRes = await fetch(acUrl, { headers });
        const acData = await acRes.json();
        setAircraft(Array.isArray(acData) ? acData : [acData]);

        // Fetch Level 2 ROIs
        const roiRes = await fetch(`http://localhost:8000/regions-of-interest?level=2`, { headers });
        const roiData = await roiRes.json();
        setRois(Array.isArray(roiData) ? roiData : []);

      } catch (error) {
        console.error("API Error:", error);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [selectedTime, showAll]);

  return (
    <div className={`${isDarkMode ? 'dark' : ''} flex h-screen w-screen bg-white dark:bg-slate-950 overflow-hidden select-none`}>
      <aside 
          style={{ 
            width: isCollapsed ? '64px' : `${sidebarWidth}px`,
            backgroundColor: isDarkMode ? THEME.modes.dark.sidebar : THEME.modes.light.sidebar,
            borderColor: isDarkMode ? THEME.modes.dark.border : THEME.modes.light.border
          }} 
          className="h-full border-r flex flex-col z-[1001] shrink-0 transition-all duration-300"
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
            <Value mode={currentMode}>View Mode</Value>
            <button 
              onClick={() => setShowAll(!showAll)}
              className={`px-3 py-1 rounded-full text-[10px] font-bold transition-all border ${
                showAll ? 'bg-blue-500/20 border-blue-500 text-blue-400' : 'bg-slate-800 border-slate-700 text-slate-400'
              }`}
            >
              {showAll ? 'ALL' : 'ACTIVE ONLY'}
            </button>
          </div>
        )}

        {!isCollapsed && (
           <div className="p-4 border-b border-slate-800 space-y-4">
              <div className="space-y-2 bg-slate-800/40 p-3 rounded-lg border border-slate-700/50">
                <div className="flex justify-between items-center text-[10px] uppercase tracking-wider font-bold text-slate-500">
                  <div className="flex items-center gap-1">
                    <Clock size={12} /> <Value mode={currentMode}>History Range</Value>
                  </div>
                  <Value mode={currentMode}>{selectedTime.label}</Value>
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
                                <Header mode={currentMode}>{ac.registration || "N/A"}</Header>
                                <div className="flex items-center gap-2 min-w-0 max-w-[55%]">
                                    <Value mode={currentMode}>{ac.airfield_name || (ac.at_airfield ? "On Ground" : "In Transit")}</Value>
                                    <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: statusColor, boxShadow: `0 0 6px ${statusColor}` }} />
                                </div>
                            </div>
                            <Value mode={currentMode}>{ac.model || "Unknown Model"}</Value>
                        </div>
                    )}
                </div>
              </div>
            );
          })}
        </div>

        {/* ROI List (Level 2) */}
        {!isCollapsed && rois.length > 0 && (
          <div className="px-3 py-2 border-b border-slate-800">
            <div className="flex items-center gap-2 mb-2 px-1">
              <Target size={14} className="text-red-400" />
              <Header mode={currentMode}>Active ROI</Header>
            </div>
            <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
              {rois.map((roi) => (
                <div 
                  key={roi.id}
                  onClick={() => {
                    setMapCenter([Number(roi.lon), Number(roi.lat)]);
                  }}
                  className="p-2 rounded bg-red-500/5 border border-red-500/20 hover:bg-red-500/10 cursor-pointer transition-all"
                >
                  <div className="flex justify-between items-center">
                    <Value mode={currentMode}>{roi.name}</Value>
                    <Label mode={currentMode}>{roi.type}</Label>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* --- Theme Toggle at Bottom of Sidebar --- */}
        <div className="p-4 border-t border-slate-800 mt-auto">
          <button 
            onClick={toggleTheme}
            className={`flex items-center justify-center gap-2 w-full py-2 rounded-lg transition-all duration-300 border ${
              isDarkMode 
                ? 'bg-slate-800 border-slate-700 text-yellow-400 hover:bg-slate-700' 
                : 'bg-slate-100 border-slate-300 text-slate-900 hover:bg-white'
            }`}
          >
            {isDarkMode ? <Sun size={16} /> : <Moon size={16} />}
            {!isCollapsed && (
              <Label mode={currentMode}>{isDarkMode ? 'Light Mode' : 'Dark Mode'}</Label>
            )}
          </button>
        </div>
      </aside>

      {/* Resizer Handle (Hidden when collapsed) */}
      {!isCollapsed && (
        <div 
          onPointerDown={startResizing} // Changed from onMouseDown
          className="w-1 cursor-col-resize bg-slate-800 hover:bg-blue-500 transition-colors z-[1002]" 
        />
      )}

      <main className="flex-1 relative h-full bg-slate-50 dark:bg-slate-900">
        {/* 4. PASS THE CENTER PROP: This tells MapComponent where to fly */}
        <MapComponent 
            aircraft={aircraft} 
            rois={rois}
            timeRangeSeconds={selectedTime.seconds} 
            center={mapCenter} 
            mode={currentMode}
        />
      </main>
    </div>
  );
}

export default App;
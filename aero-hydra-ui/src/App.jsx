import React, { useState, useEffect, useCallback } from 'react';
import { Plane, Clock, ChevronLeft, ChevronRight, Target, Sun, Moon } from 'lucide-react'; // Added Chevrons
import MapComponent from './MapComponent';

import { TRACK_COLORS, THEME } from './theme';
import { Header, Label, Value, getModeColors } from './components/Typography';


const TIME_OPTIONS = [
  { label: '5m', seconds: 300 },
  { label: '15m', seconds: 900 },
  { label: '30m', seconds: 1800 },
  { label: '1h', seconds: 3600 },
  { label: '2h', seconds: 7200 },
  { label: '3h', seconds: 10800 },
  { label: '4h', seconds: 14400 },
  { label: '6h', seconds: 21600 },
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

        const aircraftArray = Array.isArray(acData) ? acData : [acData];
        setAircraft(aircraftArray);

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

          <button 
            onClick={() => setIsCollapsed(!isCollapsed)} 
            className="p-1 rounded transition-colors duration-200 border border-transparent hover:border-slate-300 dark:hover:border-slate-700"
            style={{
              backgroundColor: getModeColors(currentMode).background
            }}
          >
            <Label mode={currentMode}>{isCollapsed ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}</Label>
          </button>
        </div>

        {/* Time Slider & and toggle */}
        {!isCollapsed && (
          <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
            <Label mode={currentMode}>View Mode</Label>
            <button 
              onClick={() => setShowAll(!showAll)}
              className={`px-3 py-1 rounded-full transition-all border ${
                showAll 
                  ? 'bg-blue-600 border-blue-600 shadow-sm' 
                  : 'border-slate-300 dark:border-slate-700'
              }`}
              style={{
                backgroundColor: getModeColors(currentMode).background
              }}
            >
              <Label mode={currentMode}>
                {showAll ? 'ALL' : 'ACTIVE ONLY'}
              </Label>
            </button>
          </div>
        )}

        {!isCollapsed && (
           <div className="p-4 border-b border-slate-200 dark:border-slate-800 space-y-4">
              <div 
                className="space-y-2 p-3 rounded-lg border transition-colors duration-200"
                style={{
                  // Dynamically switches background based on theme
                  backgroundColor: isDarkMode ? 'rgba(30, 41, 59, 0.4)' : 'rgba(241, 245, 249, 0.8)',
                  borderColor: isDarkMode ? 'rgba(51, 65, 85, 0.5)' : 'rgba(203, 213, 225, 1)'
                }}
              >
                <div className="flex justify-between items-center text-[10px] uppercase tracking-wider font-bold">
                <div className="flex items-center gap-1">
                  <Clock size={12} className={isDarkMode ? 'text-slate-500' : 'text-slate-400'} /> 
                  <Label mode={currentMode}>History Range</Label>
                </div>
                <Value mode={currentMode}>{selectedTime.label}</Value>
              </div>
                <input
                  type="range"
                  min="0"
                  max={TIME_OPTIONS.length - 1}
                  value={timeIndex}
                  onChange={(e) => setTimeIndex(Number.parseInt(e.target.value))}
                  className={`w-full h-1.5 rounded-lg appearance-none cursor-pointer accent-blue-500 transition-colors ${
                      isDarkMode ? 'bg-slate-700' : 'bg-slate-300'
                    }`}
                  />
              </div>
           </div>
        )}

        {/* Aircraft List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2 overflow-x-hidden">
          {aircraft
            .slice()
            .sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0))
            .reverse()
            .map((ac) => {
            const statusColor = getAircraftColor(ac);
            return (
              <div 
                key={ac.icao24} 
                // 1. Semantic Role
                role="button"
                // 2. Keyboard Access (makes it focusable)
                tabIndex={0}
                // 3. Mouse/Touch Click
                onClick={() => handleAircraftClick(ac)}
                // 4. Keyboard Input (Enter/Space support)
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleAircraftClick(ac);
                  }
                }}
                className={`rounded-lg border bg-slate-800/50 hover:bg-slate-800/80 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all cursor-pointer group ${isCollapsed ? 'p-2 flex justify-center' : 'p-3'}`}
                style={{ borderColor: `${statusColor}33` }}
                // Optional: Add a label for screen readers
                aria-label={`Select aircraft ${ac.callsign || ac.icao24}`}
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
        <div className="p-6 border-t border-slate-200 dark:border-slate-800 mt-auto flex shrink-0 justify-center items-center">
          {/* The Outer Track */}
          <button
            onClick={toggleTheme}
            aria-label="Toggle Theme"
            className={`
              relative flex items-center shrink-0
              h-14 w-28 rounded-full p-1 
              transition-all duration-500 ease-in-out
              focus:outline-none 
              border-4
              ${isDarkMode 
                ? 'bg-slate-900 border-blue-500 shadow-lg' 
                : 'bg-white border-slate-400 shadow-inner'
              }
            `}
          >
            {/* The Sliding Thumb */}
            <div
              className={`
                flex items-center justify-center
                rounded-full shadow-lg transform transition-all duration-500 cubic-bezier(0.34, 1.56, 0.64, 1)
                ${isDarkMode 
                  ? 'h-10 w-10 translate-x-12 bg-blue-500 text-white' 
                  : 'h-10 w-10 translate-x-0 bg-slate-100 text-orange-500'
                }
              `}
            >
              {isDarkMode ? (
                <Moon size={24} fill="currentColor" />
              ) : (
                <Sun size={24} fill="currentColor" />
              )}
            </div>

            {/* Background Icons (Stationary) */}
            <div className="absolute inset-0 flex items-center justify-between px-3 pointer-events-none opacity-20">
              <Sun size={18} className={isDarkMode ? 'text-white' : 'hidden'} />
              <Moon size={18} className={!isDarkMode ? 'text-slate-600' : 'hidden'} />
            </div>
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
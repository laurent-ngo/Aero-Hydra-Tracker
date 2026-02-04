import React, { useState, useEffect, useCallback } from 'react';
import { Plane, Clock } from 'lucide-react';
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
];

function App() {
  const [aircraft, setAircraft] = useState([]);
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [isResizing, setIsResizing] = useState(false);
  const [timeIndex, setTimeIndex] = useState(3); // Default to 1h

  const selectedTime = TIME_OPTIONS[timeIndex];

  const getStatusColor = (atAirfield) => {
    if (atAirfield === true || atAirfield === "true") return '#fb923c'; // Orange
    if (atAirfield === false || atAirfield === "false") return '#22c55e'; // Green
    return '#94a3b8'; // Gray
  };

  // --- Resizing Logic ---
  const startResizing = useCallback(() => setIsResizing(true), []);
  const stopResizing = useCallback(() => setIsResizing(false), []);
  const resize = useCallback((e) => {
    if (isResizing) {
      const newWidth = Math.min(Math.max(200, e.clientX), 600);
      setSidebarWidth(newWidth);
    }
  }, [isResizing]);

  useEffect(() => {
    window.addEventListener("mousemove", resize);
    window.addEventListener("mouseup", stopResizing);
    return () => {
      window.removeEventListener("mousemove", resize);
      window.removeEventListener("mouseup", stopResizing);
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
        style={{ width: `${sidebarWidth}px` }} 
        className="h-full bg-slate-900 border-r border-slate-800 flex flex-col z-[1001] shrink-0"
      >
        <div className="p-4 border-b border-slate-800 space-y-4">
          <h1 className="text-xl font-bold text-blue-400">AERO-HYDRA</h1>
          
          {/* Time Slider Control */}
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
              onChange={(e) => setTimeIndex(parseInt(e.target.value))}
              className="w-full h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {aircraft.map((ac) => (
            <div 
              key={ac.icao24} 
              style={{ borderColor: `${getStatusColor(ac.at_airfield)}33` }}
              className="p-3 rounded-lg border bg-slate-800/50 hover:bg-slate-800 transition-all cursor-pointer"
            >
              <div className="flex justify-between items-start">
                <div className="flex items-center gap-3">
                  <Plane 
                    size={18} 
                    style={{ 
                      color: getStatusColor(ac.at_airfield),
                      transform: 'rotate(45deg)' 
                    }}
                    className="transition-colors" 
                  />
                  <div>
                    <span className="font-mono font-bold text-slate-100">{ac.registration}</span>
                    <p className="text-[10px] text-slate-500 uppercase font-bold leading-none mt-1">
                      {ac.model}
                    </p>
                  </div>
                </div>
              </div>
              <div className="mt-2 text-[10px] text-slate-400 font-medium italic">
                {ac.airfield_name || "In Transit"}
              </div>
            </div>
          ))}
        </div>
      </aside>

      <div
        onMouseDown={startResizing}
        className="w-1 cursor-col-resize bg-slate-800 hover:bg-blue-500 transition-colors z-[1002]"
      />

      <main className="flex-1 relative h-full bg-slate-900">
        <MapComponent 
          aircraft={aircraft} 
          timeRangeSeconds={selectedTime.seconds} 
        />
      </main>
    </div>
  );
}

export default App;
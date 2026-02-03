import React, { useState, useEffect, useCallback } from 'react';
import MapComponent from './MapComponent';

function App() {
  const [aircraft, setAircraft] = useState([]);
  const [sidebarWidth, setSidebarWidth] = useState(320); // Initial width in pixels
  const [isResizing, setIsResizing] = useState(false);

  // --- Resizing Logic ---
  const startResizing = useCallback(() => {
    setIsResizing(true);
  }, []);

  const stopResizing = useCallback(() => {
    setIsResizing(false);
  }, []);

  const resize = useCallback((mouseMoveEvent) => {
    if (isResizing) {
      // Clamp width between 200px and 600px for a better UI
      const newWidth = Math.min(Math.max(200, mouseMoveEvent.clientX), 600);
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

  // --- Data Fetching ---
  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch('http://localhost:8000/aircraft');
        const data = await response.json();
        setAircraft(Array.isArray(data) ? data : (data ? [data] : []));
      } catch (error) {
        console.error("API Error:", error);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex h-screen w-screen bg-slate-950 overflow-hidden select-none">
      
      {/* 1. The Adjustable Sidebar */}
      <aside 
        style={{ width: `${sidebarWidth}px` }} 
        className="h-full bg-slate-900 border-r border-slate-800 flex flex-col z-[1001] shrink-0"
      >
        <div className="p-4 border-b border-slate-800">
          <h1 className="text-xl font-bold text-blue-400">AERO-HYDRA</h1>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {aircraft.map((ac) => (
            <div 
              key={ac.icao24} 
              className="p-3 bg-slate-800/50 hover:bg-slate-800 rounded-lg border border-slate-700/30 transition-all cursor-pointer group"
            >
              <div className="flex justify-between items-start">
                <span className="font-mono text-blue-400 font-bold">{ac.registration}</span>
                <div className={`w-2 h-2 rounded-full mt-1.5 ${ac.last_lat ? 'bg-green-500 shadow-[0_0_8px_#22c55e]' : 'bg-slate-600'}`}></div>
              </div>
              
              <p className="text-sm text-slate-200 truncate mt-1">{ac.model}</p>
              
              {/* Last Airfield Display */}
              <div className="mt-3 flex items-center gap-2 text-slate-400">
                <div className="overflow-hidden">
                  <p className="text-[10px] uppercase text-slate-500 font-bold leading-none">Last Airfield</p>
                  <p className="text-xs truncate font-medium">
                    {ac.airfield_name && ac.airfield_name !== "Unknown" ? ac.airfield_name : (ac.last_airfield || "unknown")}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </aside>

      {/* 2. The Invisible Resizer Bar */}
      <div
        onMouseDown={startResizing}
        className="w-1 cursor-col-resize bg-slate-800 hover:bg-blue-500 transition-colors z-[1002]"
      />

      {/* 3. The Main Map Area */}
      <main className="flex-1 relative h-full bg-slate-900">
        <MapComponent aircraft={aircraft} />
      </main>
    </div>
  );
}

export default App;
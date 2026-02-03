import React, { useState, useEffect, useCallback } from 'react';
import { Plane } from 'lucide-react';
import MapComponent from './MapComponent';

function App() {
  const [aircraft, setAircraft] = useState([]);
  const [sidebarWidth, setSidebarWidth] = useState(320); // Initial width in pixels
  const [isResizing, setIsResizing] = useState(false);


  
  const getStatusColor = (atAirfield) => {
    if (atAirfield === true || atAirfield === "true") return '#fb923c'; // Orange
    if (atAirfield === false || atAirfield === "false") return '#22c55e'; // Green
    return '#94a3b8'; // Gray (for null/None)
  };
  
  const getStatusLabel = (atAirfield) => {
    if (atAirfield === true) return 'Ground';
    if (atAirfield === false) return 'Airborne';
    return 'Unknown';
  };
  
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
          {aircraft.map((ac) => {
            const isOnGround = ac.at_airfield === true;

            return (
              <div 
                key={ac.icao24} 
                style={{ borderColor: `${getStatusColor(ac.at_airfield)}33` }} // Adds 20% opacity to border
                className="p-3 rounded-lg border bg-slate-800/50 hover:bg-slate-800 transition-all cursor-pointer"
              >
                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-3">
                    {/* Plane Icon: Rotated 45deg to look like it's taking off */}
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

                <div className="mt-3 flex flex-col gap-1">
                  <div className="flex justify-between text-[10px]">
                    <span className="text-slate-300 truncate max-w-[120px]">
                      {ac.airfield_name || "Unknown"}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
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
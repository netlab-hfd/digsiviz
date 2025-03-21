import React, { useEffect, useState } from "react";
import io from "socket.io-client";
import "./index.css"

const socket = io("http://localhost:5000"); // Passe die URL an

const TimeMachine: React.FC = () => {
    const [isLive, setIsLive] = useState(true);
    const [timestamps, setTimestamps] = useState<number[]>([]);
    const [selectedTimestamp, setSelectedTimestamp] = useState<number | null>(null);

    useEffect(() => {
        socket.on("available_timestamps", (data) => {
            setTimestamps(data.values);
            if (isLive) {
                setSelectedTimestamp(data.values[data.values.length - 1]);
            }
        });
        return () => {
            socket.off("available_timestamps");
        };
    }, [isLive]);

    const handleToggleLive = () => {
        if (isLive) {
            setIsLive(false);
            socket.emit("timemachine", { time_machine_active: true });
            setSelectedTimestamp(timestamps[timestamps.length - 1] || null);
        } else {
            setIsLive(true);
            socket.emit("timemachine", { time_machine_active: false });
            setSelectedTimestamp(null);
        }
    };

    const handleTimestampChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
        const newTimestamp = Number(event.target.value);
        setSelectedTimestamp(newTimestamp);
        socket.emit("timestamp", { timestamp: newTimestamp });
    };

    const stepBackward = () => {
        if (!timestamps.length || selectedTimestamp === null) return;
        const currentIndex = timestamps.indexOf(selectedTimestamp);
        if (currentIndex > 0) {
            const newTimestamp = timestamps[currentIndex - 1];
            setSelectedTimestamp(newTimestamp);
            socket.emit("timestamp", { timestamp: newTimestamp });
        }
    };

    const stepForward = () => {
        if (!timestamps.length || selectedTimestamp === null) return;
        const currentIndex = timestamps.indexOf(selectedTimestamp);
        if (currentIndex < timestamps.length - 1) {
            const newTimestamp = timestamps[currentIndex + 1];
            setSelectedTimestamp(newTimestamp);
            socket.emit("timestamp", { timestamp: newTimestamp });
        }
    };

    return (
        <div className="flex flex-row items-center justify-center gap-4">
            <button
                onClick={handleToggleLive}
                className={`shrink-0 px-4 py-2 rounded-md ${
                    !isLive ?  'bg-emerald-500 hover:bg-emerald-600' : 'bg-red-500 hover:bg-red-600'
                } text-white font-medium transition-colors`}
            >
                {isLive ? "Stop Live" : "Start Live"}
            </button>

            {!isLive && timestamps.length > 0 && (
                <>
                    <select
                        value={selectedTimestamp || ""}
                        onChange={handleTimestampChange}
                        className="w-48 px-3 py-2 bg-white border border-gray-300 rounded-md text-gray-900 focus:ring-2 focus:ring-gray-400 focus:border-gray-400"
                    >
                        {timestamps.map((ts) => (
                            <option key={ts} value={ts}>
                                {new Date(ts * 1000).toISOString().substr(11, 12)}
                            </option>
                        ))}
                    </select>

                    <button
                        onClick={stepBackward}
                        className="px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-md transition-colors"
                    >
                        ←
                    </button>
                    <button
                        onClick={stepForward}
                        className="px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-md transition-colors"
                    >
                        →
                    </button>
                </>
            )}
        </div>
    );
};

export default TimeMachine;

import React, { useEffect, useState, useMemo } from "react";
import io from "socket.io-client";
import { Sparklines, SparklinesLine } from "react-sparklines";

const socket = io("http://127.0.0.1:5000");

const TimeMachineStats: React.FC = () => {
    const [stdDeviation, setStdDeviation] = useState<number | null>(null);
    const [history, setHistory] = useState<number[]>([]);

    useEffect(() => {
        socket.on("timemachine_stats", (data) => {
            if (data?.deviation !== undefined) {
                const deviation = data.deviation;
                setStdDeviation(deviation);

                setHistory(prev => {
                    const updated = [...prev, deviation];
                    return updated.length > 120 ? updated.slice(updated.length - 120) : updated;
                });
            }
        });

        return () => {
            socket.off("timemachine_stats");
        };
    }, []);

    const average = useMemo(() => {
        if (history.length === 0) return null;
        const sum = history.reduce((acc, val) => acc + val, 0);
        return sum / history.length;
    }, [history]);

    return (
        <div className="fixed top-4 right-4 z-50 bg-black bg-opacity-75 text-white px-4 py-3 rounded-md text-sm font-mono shadow-lg w-60">
            <div className="font-semibold mb-1 text-center">Std Dev.</div>
            <div className="text-center text-lg">
                {stdDeviation !== null ? stdDeviation.toFixed(4) : "–"}
            </div>

            <div className="mt-2">
                <Sparklines data={history} limit={120} height={100}>
                    <SparklinesLine color="cyan" style={{ strokeWidth: 1.5, fill: "none" }} />
                </Sparklines>
            </div>

            <div className="font-semibold mt-3 mb-1 text-center">Avg. Std Dev.</div>
            <div className="text-center text-lg">
                {average !== null ? average.toFixed(4) : "–"}
            </div>

        </div>
    );
};

export default TimeMachineStats;

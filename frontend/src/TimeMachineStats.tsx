import React, { useEffect, useState, useMemo } from "react";
import io from "socket.io-client";
import { Sparklines, SparklinesLine } from "react-sparklines";

const socket = io("http://127.0.0.1:5000");

const TimeMachineStats: React.FC = () => {
    const [stdDeviation, setStdDeviation] = useState<number | null>(null);
    const [backendTimestamp, setBackendTimestamp] = useState<number | null>(null);
    const [backendCycleDuration, setBackendCycleDuration] = useState<number | null>(null);
    const [frontendTimestamp, setFrontendTimestamp] = useState<number | null>(null);
    const [minTimestamp, setMinTimestamp] = useState<number | null>(null);
    const [timeStampDiff, setTimeStampDiff] = useState<number | null>(null);
    const [cycleStartTime, setCycleStartTime] = useState<number | null>(null);
    const [cycleStartToRenderDifference, setCycleStartToRenderDifference] = useState<number | null>(null);
    const [pollDuration, setPollDuration] = useState<number | null>(null);
    const [history, setHistory] = useState<number[]>([]);

    useEffect(() => {
        socket.on("timemachine_stats", (data) => {
            const now = Date.now()
            setFrontendTimestamp(now);
            if (data?.deviation !== undefined) {
                const deviation = data.deviation;
                setStdDeviation(deviation);

                setHistory(prev => {
                    const updated = [...prev, deviation];
                    return updated.length > 120 ? updated.slice(updated.length - 120) : updated;
                });
            }

            if (data?.min_timestamp !== undefined) {
                const minTs = data.min_timestamp
                setMinTimestamp(minTs);
                const minRouterToRenderDifference = now - (minTs/1e6)
                setTimeStampDiff(minRouterToRenderDifference);


            }


            if(data?.cycle_starttime != undefined){
                const cycleStartTime = data.cycle_starttime;
                setCycleStartTime(cycleStartTime);
                const cycleStartToRenderDifference = now - (cycleStartTime * 1000);
                setCycleStartToRenderDifference(cycleStartToRenderDifference);

            }

            if (data?.general_timestamp !== undefined) {
                const backendTs = data.general_timestamp;
                setBackendTimestamp(backendTs);
            }

            if(data?.cycle_duration_ms != undefined){
                const backendCycleDuration = data.cycle_duration_ms;
                setBackendCycleDuration(backendCycleDuration);
            }

            if(data?.poll_duration != undefined){
                const pollDuration = data.poll_duration;
                setPollDuration(pollDuration);
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
            <div className="font-bold text-xl mt-3 mb-1 text-center text-decoration-underline">NDT Values</div>
            <div className="font-semibold mb-1 text-center">Std Dev. between routers</div>
            <div className="text-center text-lg">
                {stdDeviation !== null ? stdDeviation.toFixed(4) : "–"}
            </div>

            <div className="mt-2">
                <Sparklines data={history} limit={120} height={100}>
                    <SparklinesLine color="cyan" style={{ strokeWidth: 1.5, fill: "none" }} />
                </Sparklines>
            </div>

            <div className="font-semibold mt-3 mb-1 text-center">Avg. Std Dev. between routers</div>
            <div className="text-center text-lg">
                {average !== null ? average.toFixed(4) : "–"}
            </div>

            <div className="font-semibold mt-3 mb-1 text-center">Min Router Timestamp</div>
            <div className="text-center text-xs">
                {minTimestamp}
            </div>

            <div className="font-bold text-xl mt-3 mb-1 text-center text-decoration-underline">Backend Values</div>
            <div className="font-semibold mt-3 mb-1 text-center">Polling Cycle Start Time</div>
            <div className="text-center text-xs">
                {cycleStartTime}
            </div>

            <div className="font-semibold mt-3 mb-1 text-center">gNMI General Timestamp</div>
            <div className="text-center text-xs">
                {backendTimestamp}
            </div>

            <div className="font-semibold mt-3 mb-1 text-center">gNMI Poll Duration</div>
            <div className="text-center text-xs">
                {pollDuration} s
            </div>

            <div className="font-semibold mt-3 mb-1 text-center">Backend Cycle Duration</div>
            <div className="text-center text-xs">
                {backendCycleDuration} ms
            </div>




            <div className="font-semibold mt-3 mb-1 text-center">Current Frontend Timestamp</div>
            <div className="text-center text-xs">
                {frontendTimestamp}
            </div>


            <div className="font-bold text-xl mt-3 mb-1 text-center text-decoration-underline">Durations</div>

                <div className="font-semibold mt-3 mb-1 text-center">Min Router Timestamp to Render Duration</div>
                <div className="text-center text-xs">
                    {timeStampDiff} ms
                </div>



            <div className="font-semibold mt-3 mb-1 text-center">Cycle Start Time to Render Duration</div>
            <div className="text-center text-xs">
                {cycleStartToRenderDifference} ms
            </div>




        </div>
    );
};

export default TimeMachineStats;

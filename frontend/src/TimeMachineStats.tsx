import React, {useEffect, useState, useMemo} from "react";
import io from "socket.io-client";
import {Sparklines, SparklinesLine} from "react-sparklines";

const socket = io("http://127.0.0.1:5000");

const TimeMachineStats: React.FC = () => {
    const [routerTimeStampStdDeviation, setRouterTimeStampStdDeviation] = useState<number | null>(null);
    const [routerTimeStampStdDeviationHistory, setRouterTimeStampStdDeviationHistory] = useState<number[]>([]);
    const [gnmiDataCollectionTimeStamp, setGnmiDataCollectionTimeStamp] = useState<number | null>(null);
    const [backendDataPollingCycleDuration, setBackendDataPollingCycleDuration] = useState<number | null>(null);
    const [frontendTimestamp, setFrontendTimestamp] = useState<number | null>(null);
    const [minRouterTimeStamp, setMinRouterTimeStamp] = useState<number | null>(null);
    const [minRouterTimeStampToRenderDuration, setMinRouterTimeStampToRenderDuration] = useState<number | null>(null);
    const [backendDataPollingCycleStartTime, setBackendDataPollingCycleStartTime] = useState<number | null>(null);
    const [backendDataPollingCycleStartToRenderDuration, setBackendDataPollingCycleStartToRenderDuration] = useState<number | null>(null);
    const [gnmiPollingDuration, setGnmiPollingDuration] = useState<number | null>(null);

    const [csvLogData, setCsvLogData] = useState<any[]>([]);


    const formatTimestamp = (timestampMs: number | null) => {
        if (!timestampMs) return "–";
        const date = new Date(timestampMs);
        const timeStr = date.toLocaleTimeString();
        const ms = date.getMilliseconds().toString().padStart(3, "0");
        return `${timeStr}.${ms}`;
    };


    useEffect(() => {
        socket.on("timemachine_stats", (data) => {

            const now = Date.now()
            setFrontendTimestamp(now);

            if (data?.router_timestamp_deviation_ms !== undefined) {
                const deviation = data.router_timestamp_deviation_ms;
                setRouterTimeStampStdDeviation(deviation);

                setRouterTimeStampStdDeviationHistory(prev => {
                    const updated = [...prev, deviation];
                    return updated.length > 120 ? updated.slice(updated.length - 120) : updated;
                });
            }

            if (data?.min_router_timestamp_ms !== undefined) {
                const minTs = data.min_router_timestamp_ms
                setMinRouterTimeStamp(minTs);
                const minRouterTsToRenderDuration = now - minTs
                setMinRouterTimeStampToRenderDuration(minRouterTsToRenderDuration);


            }


            if (data?.datapolling_cycle_starttime_ms != undefined) {
                const cycleStartTime = data.datapolling_cycle_starttime_ms;
                setBackendDataPollingCycleStartTime(cycleStartTime);

                const cycleStartToRenderDuration = now - cycleStartTime;
                setBackendDataPollingCycleStartToRenderDuration(cycleStartToRenderDuration);

            }

            if (data?.gnmi_data_collection_timestamp_ms !== undefined) {
                const backendTs = data.gnmi_data_collection_timestamp_ms;
                setGnmiDataCollectionTimeStamp(backendTs);
            }

            if (data?.datapolling_cycle_duration_ms != undefined) {
                const dataPollingCycleDuration = data.datapolling_cycle_duration_ms;
                setBackendDataPollingCycleDuration(dataPollingCycleDuration);
            }

            if (data?.gnmi_polling_duration_ms != undefined) {
                const pollDuration = data.gnmi_polling_duration_ms;
                setGnmiPollingDuration(pollDuration);
            }


            //Log to CSV
            const csvRow = {
                datapolling_cycle_starttime_ms: formatTimestamp(data?.datapolling_cycle_starttime_ms),
                min_router_timestamp_ms: formatTimestamp(data?.min_router_timestamp_ms),
                gnmi_data_collection_timestamp_ms: formatTimestamp(data?.gnmi_data_collection_timestamp_ms),
                frontend_timestamp: formatTimestamp(now),
                router_timestamp_deviation_ms: data?.router_timestamp_deviation_ms,
                gnmi_polling_duration_ms: data?.gnmi_polling_duration_ms,
                datapolling_cycle_duration_ms: data?.datapolling_cycle_duration_ms,
                min_router_timestamp_to_render_duration: now - data?.min_router_timestamp_ms,
                cycle_start_to_render_duration: now - data?.datapolling_cycle_starttime_ms,

            }
            setCsvLogData(prev => [...prev, csvRow]);

        });

        return () => {
            socket.off("timemachine_stats");
        };
    }, []);

    const average = useMemo(() => {
        if (routerTimeStampStdDeviationHistory.length === 0) return null;
        const sum = routerTimeStampStdDeviationHistory.reduce((acc, val) => acc + val, 0);
        return sum / routerTimeStampStdDeviationHistory.length;
    }, [routerTimeStampStdDeviationHistory]);


    const saveCsv = () => {
        if (csvLogData.length === 0) return;

        const headers = Object.keys(csvLogData[0]);

        const formatValue = (value: any) => {
            if (typeof value === "number") {
                return value.toString().replace(".", ",");
            }
            if (typeof value === "string" && /^\d+\.\d+$/.test(value)) {
                return value.replace(".", ",");
            }
            return value;
        };

        const csvContent = [
            headers.join(";"),
            ...csvLogData.map(row =>
                headers.map(h => formatValue(row[h])).join(";")
            )
        ].join("\n");

        const blob = new Blob([csvContent], {type: "text/csv;charset=utf-8;"});
        const url = URL.createObjectURL(blob);

        const link = document.createElement("a");
        link.setAttribute("href", url);
        link.setAttribute("download", `timemachine_log_${new Date().toISOString()}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };


    return (
        <div
            className="fixed top-4 right-4 z-50 bg-black bg-opacity-75 text-white px-4 py-3 rounded-md text-sm font-mono shadow-lg w-60">
            <div className="font-bold text-xl mt-3 mb-1 text-center text-decoration-underline">NDT Values</div>
            <div className="font-semibold mb-1 text-center">Std Dev. between routers</div>
            <div className="text-center text-lg">
                {routerTimeStampStdDeviation !== null ? routerTimeStampStdDeviation.toFixed(4) : "–"} ms
            </div>

            <div className="mt-2">
                <Sparklines data={routerTimeStampStdDeviationHistory} limit={120} height={100}>
                    <SparklinesLine color="cyan" style={{strokeWidth: 1.5, fill: "none"}}/>
                </Sparklines>
            </div>

            <div className="font-semibold mt-3 mb-1 text-center">Avg. Std Dev. between routers</div>
            <div className="text-center text-lg">
                {average !== null ? average.toFixed(4) : "–"} ms
            </div>

            <div className="font-semibold mt-3 mb-1 text-center">Min Router Timestamp</div>
            <div className="text-center text-xs">
                {formatTimestamp(minRouterTimeStamp)}
            </div>

            <div className="font-bold text-xl mt-3 mb-1 text-center text-decoration-underline">App Values</div>
 {/*           <div className="font-semibold mt-3 mb-1 text-center">Polling Cycle Start Time</div>
            <div className="text-center text-xs">
                {formatTimestamp(backendDataPollingCycleStartTime)}
            </div>*/}

            <div className="font-semibold mt-3 mb-1 text-center">gNMI General (End) Timestamp</div>
            <div className="text-center text-xs">
                {formatTimestamp(gnmiDataCollectionTimeStamp)}
            </div>

            <div className="font-semibold mt-3 mb-1 text-center">gNMI Poll Duration</div>
            <div className="text-center text-xs">
                {gnmiPollingDuration} ms
            </div>

{/*            <div className="font-semibold mt-3 mb-1 text-center">Backend Cycle Duration</div>
            <div className="text-center text-xs">
                {backendDataPollingCycleDuration} ms
            </div>*/}


            <div className="font-semibold mt-3 mb-1 text-center">Current Frontend Timestamp</div>
            <div className="text-center text-xs">
                {formatTimestamp(frontendTimestamp)}
            </div>


            <div className="font-bold text-xl mt-3 mb-1 text-center text-decoration-underline">Durations</div>

            <div className="font-semibold mt-3 mb-1 text-center">Min Router Timestamp to Render Duration</div>
            <div className="text-center text-xs">
                {minRouterTimeStampToRenderDuration} ms
            </div>


 {/*           <div className="font-semibold mt-3 mb-1 text-center">Cycle Start Time to Render Duration</div>
            <div className="text-center text-xs">
                {backendDataPollingCycleStartToRenderDuration} ms
            </div>*/}

            <button
                onClick={saveCsv}
                className="mt-4 w-full bg-cyan-700 hover:bg-cyan-800 text-white py-1 px-2 rounded"
            >
                Save CSV
            </button>


        </div>
    );
};

export default TimeMachineStats;

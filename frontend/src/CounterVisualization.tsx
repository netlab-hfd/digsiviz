import React, {useEffect, useState, useRef} from "react";
import {Sparklines, SparklinesLine, SparklinesSpots, SparklinesReferenceLine} from "react-sparklines";

interface Link {
    source: string;
    target: string;
    source_interface: string;
    target_interface: string;
}

interface CounterVisualizationProps {
    routerData: any;
    selectedNode: string | null;
    selectedLink: Link | null;
}

interface Counters {
    inDiscards: number;
    inErrors: number;
    inOctets: number;
    inPkts: number;
    outDiscards: number;
    outErrors: number;
    outOctets: number;
    outPkts: number;
}

interface InterfaceData {
    name: string;
    timestamp: number;
    counters: Counters;
}

interface TrafficRate {
    inRate: number;
    outRate: number;
    inRateMbps: number;
    outRateMbps: number;
}

const CounterVisualization: React.FC<CounterVisualizationProps> = ({routerData, selectedNode, selectedLink}) => {
    const [selectedRouterData, setSelectedRouterData] = React.useState<any>(null);
    const [allInterfaceData, setAllInterfaceData] = React.useState<{ [key: string]: InterfaceData }>({});
    const [interfaceHistories, setInterfaceHistories] = React.useState<{ [key: string]: InterfaceData[] }>({});
    const [trafficRates, setTrafficRates] = React.useState<{ [key: string]: TrafficRate }>({});
    const [trafficRateHistories, setTrafficRateHistories] = React.useState<{ [key: string]: TrafficRate[] }>({});

    // Drag functionality states
    const [position, setPosition] = useState({ x: 384, y: 16 });
    const [isDragging, setIsDragging] = useState(false);
    const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
    const dragRef = useRef<HTMLDivElement>(null);

    // Interface selection states
    const [selectedInterfaces, setSelectedInterfaces] = useState<Set<string>>(new Set());
    const [showInterfaceSelector, setShowInterfaceSelector] = useState(false);

    useEffect(() => {
        setAllInterfaceData({});
        setInterfaceHistories({});
        setTrafficRates({});
        setTrafficRateHistories({});
        setSelectedRouterData(null);
        setSelectedInterfaces(new Set());
    }, [selectedNode]);

    useEffect(() => {
        if (routerData != null && selectedNode != null) {
            // console.log("Node selected:", selectedNode);
            const currentRouterData = routerData[selectedNode];
            setSelectedRouterData(currentRouterData);

            if (currentRouterData) {
                const newAllInterfaceData: { [key: string]: InterfaceData } = {};

                Object.keys(currentRouterData).forEach((interfaceName) => {
                    const interfaceData = currentRouterData[interfaceName];
                    if (interfaceData && interfaceData["openconfig-interfaces:state"] && interfaceData["openconfig-interfaces:state"]["counters"]) {
                        // console.log(`Interface: ${interfaceName}, Data:`, interfaceData);

                        const newInterfaceData: InterfaceData = {
                            name: interfaceName,
                            timestamp: interfaceData["timestamp"] || Date.now(),
                            counters: {
                                inDiscards: interfaceData["openconfig-interfaces:state"]["counters"]["in-discards"] || 0,
                                inErrors: interfaceData["openconfig-interfaces:state"]["counters"]["in-errors"] || 0,
                                inOctets: interfaceData["openconfig-interfaces:state"]["counters"]["in-octets"] || 0,
                                inPkts: interfaceData["openconfig-interfaces:state"]["counters"]["in-pkts"] || 0,
                                outDiscards: interfaceData["openconfig-interfaces:state"]["counters"]["out-discards"] || 0,
                                outErrors: interfaceData["openconfig-interfaces:state"]["counters"]["out-errors"] || 0,
                                outOctets: interfaceData["openconfig-interfaces:state"]["counters"]["out-octets"] || 0,
                                outPkts: interfaceData["openconfig-interfaces:state"]["counters"]["out-pkts"] || 0
                            }
                        };

                        newAllInterfaceData[interfaceName] = newInterfaceData;

                        setInterfaceHistories(prevHistories => {
                            const currentHistory = prevHistories[interfaceName] || [];
                            const updatedHistory = [...currentHistory, newInterfaceData];
                            const limitedHistory = updatedHistory.length > 120 ? updatedHistory.slice(updatedHistory.length - 120) : updatedHistory;

                            return {
                                ...prevHistories,
                                [interfaceName]: limitedHistory
                            };
                        });
                    }
                });

                setAllInterfaceData(newAllInterfaceData);

                if (selectedInterfaces.size === 0) {
                    setSelectedInterfaces(new Set(Object.keys(newAllInterfaceData)));
                }

                // console.log(newAllInterfaceData);
            }
        }
    }, [routerData, selectedNode, selectedLink, selectedInterfaces]);

    useEffect(() => {
        const newTrafficRates: { [key: string]: TrafficRate } = {};

        Object.keys(allInterfaceData).forEach((interfaceName) => {
            const history = interfaceHistories[interfaceName] || [];
            if (history.length >= 2) {
                const current = history[history.length - 1];
                const previous = history[history.length - 2];

                const timeDiffSeconds = (current.timestamp - previous.timestamp) / 1000000000; // Nanoseconds to seconds

                /* console.log(`Interface ${interfaceName}:`);
                 console.log(`  Current timestamp: ${current.timestamp}`);
                 console.log(`  Previous timestamp: ${previous.timestamp}`);
                 console.log(`  Time diff (nanoseconds): ${current.timestamp - previous.timestamp}`);
                 console.log(`  Time diff (seconds): ${timeDiffSeconds}`);
                 console.log(`  Current inOctets: ${current.counters.inOctets}`);
                 console.log(`  Previous inOctets: ${previous.counters.inOctets}`);*/

                if (timeDiffSeconds > 0) {
                    const inOctetsDiff = Math.max(0, current.counters.inOctets - previous.counters.inOctets);
                    const outOctetsDiff = Math.max(0, current.counters.outOctets - previous.counters.outOctets);

                    /*                  console.log(`  inOctets diff: ${inOctetsDiff}`);
                                        console.log(`  outOctets diff: ${outOctetsDiff}`);*/

                    const inRateBps = inOctetsDiff / timeDiffSeconds;
                    const outRateBps = outOctetsDiff / timeDiffSeconds;
                    /*                  console.log(`  inRate B/s: ${inRateBps}`);
                                        console.log(`  outRate B/s: ${outRateBps}`);*/

                    // Convert to Mbps
                    const inRateMbps = (inRateBps * 8) / 1000000;
                    const outRateMbps = (outRateBps * 8) / 1000000;

                    // Convert to Gbps
                    const inRateGbps = inRateMbps / 1000;
                    const outRateGbps = outRateMbps / 1000;

                    /*console.log(`  inRate Mbps: ${inRateMbps}`);
                    console.log(`  inRate Gbps: ${inRateGbps}`);*/

                    newTrafficRates[interfaceName] = {
                        inRate: inRateBps,
                        outRate: outRateBps,
                        inRateMbps: inRateMbps,
                        outRateMbps: outRateMbps
                    };

                    setTrafficRateHistories(prev => {
                        const currentRateHistory = prev[interfaceName] || [];
                        const updatedRateHistory = [...currentRateHistory, newTrafficRates[interfaceName]];
                        const limitedRateHistory = updatedRateHistory.length > 120 ?
                            updatedRateHistory.slice(updatedRateHistory.length - 120) : updatedRateHistory;

                        return {
                            ...prev,
                            [interfaceName]: limitedRateHistory
                        };
                    });
                }
            }
        });

        setTrafficRates(newTrafficRates);
    }, [interfaceHistories, allInterfaceData]);

    // Drag handlers (unchanged)
    const handleMouseDown = (e: React.MouseEvent) => {
        if (dragRef.current) {
            const rect = dragRef.current.getBoundingClientRect();
            setDragOffset({
                x: e.clientX - rect.left,
                y: e.clientY - rect.top
            });
            setIsDragging(true);
        }
    };

    const handleMouseMove = (e: MouseEvent) => {
        if (isDragging) {
            const newX = e.clientX - dragOffset.x;
            const newY = e.clientY - dragOffset.y;

            const maxX = window.innerWidth - 384;
            const maxY = window.innerHeight - 100;

            setPosition({
                x: Math.max(0, Math.min(newX, maxX)),
                y: Math.max(0, Math.min(newY, maxY))
            });
        }
    };

    const handleMouseUp = () => {
        setIsDragging(false);
    };

    useEffect(() => {
        if (isDragging) {
            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
        }

        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isDragging, dragOffset]);

    useEffect(() => {
        if (selectedLink) {
            // console.log("Selected link:", selectedLink);
            // console.log("Selected node:", selectedNode);
            if (selectedNode != selectedLink.source.id) {
                const displayedInterface = selectedLink.target_interface;
                setSelectedInterfaces(new Set([displayedInterface]));
            } else {
                const displayedInterface = selectedLink.source_interface;
                setSelectedInterfaces(new Set([displayedInterface]));
            }
        }
    }, [selectedLink]);

    const toggleInterface = (interfaceName: string) => {
        setSelectedInterfaces(prev => {
            const newSet = new Set(prev);
            if (newSet.has(interfaceName)) {
                newSet.delete(interfaceName);
            } else {
                newSet.add(interfaceName);
            }
            return newSet;
        });
    };

    const getInterfaceData = (interfaceName: string, counterType: keyof Counters) => {
        const history = interfaceHistories[interfaceName] || [];
        return history.filter(item => item != null && item.counters).map(item => item.counters[counterType]);
    };

    const getTrafficRateData = (interfaceName: string, rateType: 'inRateMbps' | 'outRateMbps') => {
        const rateHistory = trafficRateHistories[interfaceName] || [];
        return rateHistory.map(rate => rate[rateType]);
    };

    const calculateAverage = (data: number[]): number => {
        if (data.length === 0) return 0;
        const sum = data.reduce((acc, value) => acc + value, 0);
        return sum / data.length;
    };

    const formatRate = (rateBps: number): string => {
        if (rateBps >= 1024 * 1024) {
            return `${(rateBps / (1024 * 1024)).toFixed(2)} MB/s`;
        } else if (rateBps >= 1024) {
            return `${(rateBps / 1024).toFixed(2)} KB/s`;
        } else {
            return `${rateBps.toFixed(2)} B/s`;
        }
    };

    const formatRateMbps = (rateMbps: number): string => {
        if (rateMbps >= 1000) {
            return `${(rateMbps / 1000).toFixed(2)} Gbit/s`;
        } else {
            return `${rateMbps.toFixed(2)} Mbit/s`;
        }
    };

    const interfaceNames = Object.keys(allInterfaceData);
    const displayedInterfaces = interfaceNames.filter(name => selectedInterfaces.has(name));

    return (
        <>
            <div
                ref={dragRef}
                className={`fixed z-50 bg-black bg-opacity-75 text-white rounded-md text-sm font-mono shadow-lg w-64 max-h-screen overflow-hidden ${isDragging ? 'cursor-grabbing select-none' : ''}`}
                style={{
                    left: `${position.x}px`,
                    top: `${position.y}px`,
                }}
            >
                {/* Draggable Header */}
                <div
                    className={`px-4 py-1 bg-gray-800 border-b border-gray-600 ${isDragging ? 'cursor-grabbing' : 'cursor-grab'} select-none`}
                    onMouseDown={handleMouseDown}
                >
                    <div className="flex items-center justify-between">
                        <div className="text-sm font-semibold">
                            {selectedNode ? `Node: ${selectedNode}` : 'Network Monitor'}
                        </div>
                        <div className="flex items-center gap-2">
                            {interfaceNames.length > 0 && (
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setShowInterfaceSelector(!showInterfaceSelector);
                                    }}
                                    className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700 transition-colors"
                                >
                                    Select
                                </button>
                            )}
                        </div>
                    </div>
                </div>

                {/* Interface Selector */}
                {showInterfaceSelector && interfaceNames.length > 0 && (
                    <div className="px-4 py-3 bg-gray-900 border-b border-gray-600">
                        <div className="flex items-center justify-between mb-2">
                            <div className="text-xs font-semibold text-gray-300">Interface Selection</div>
                        </div>
                        <div className="space-y-1 max-h-32 overflow-y-auto">
                            {interfaceNames.map((interfaceName) => (
                                <label key={interfaceName} className="flex items-center gap-2 cursor-pointer text-xs hover:bg-gray-800 p-1 rounded">
                                    <input
                                        type="checkbox"
                                        checked={selectedInterfaces.has(interfaceName)}
                                        onChange={() => toggleInterface(interfaceName)}
                                        className="w-3 h-3 text-cyan-600 bg-gray-700 border-gray-600 rounded focus:ring-cyan-500 focus:ring-2"
                                    />
                                    <span className={selectedInterfaces.has(interfaceName) ? 'text-white' : 'text-gray-400'}>
                                        {interfaceName}
                                    </span>
                                </label>
                            ))}
                        </div>
                    </div>
                )}

                {/* Content area with scroll */}
                <div className="px-2 py-2 max-h-96 overflow-y-auto">
                    {interfaceNames.length === 0 && (
                        <div className="text-center text-gray-400 text-sm">
                            No interface data available
                        </div>
                    )}

                    {displayedInterfaces.length === 0 && interfaceNames.length > 0 && (
                        <div className="text-center text-gray-400 text-sm">
                            No interfaces selected. Use the "Select" button to choose interfaces.
                        </div>
                    )}

                    {displayedInterfaces.map((interfaceName) => {
                        const interfaceData = allInterfaceData[interfaceName];
                        const history = interfaceHistories[interfaceName] || [];
                        const currentRate = trafficRates[interfaceName];

                        const inRateData = getTrafficRateData(interfaceName, 'inRateMbps');
                        const outRateData = getTrafficRateData(interfaceName, 'outRateMbps');
                        const avgInRate = calculateAverage(inRateData);
                        const avgOutRate = calculateAverage(outRateData);

                        if (!interfaceData) return null;

                        return (
                            <div key={interfaceName} className="border-gray-600 border-b-2">
                                <div className="text-sm text-left px-1 font-semibold text-white">
                                    {interfaceName}
                                </div>

                                {/* Sparklines */}
                                {history.length > 0 && (
                                    <div className="space-y-2">
                                        <div>
                                            {currentRate && (
                                                <div className="px-1 py-1 text-left text-xs">
                                                    <div className="text-green-300 flex justify-between">
                                                        <span>↓ In: {formatRateMbps(currentRate.inRateMbps)}</span>
                                                        <span className="text-gray-400">Ø {formatRateMbps(avgInRate)}</span>
                                                    </div>
{/*                                                    <div className="text-gray-500 text-xs">
                                                        ({formatRate(currentRate.inRate)})
                                                    </div>*/}
                                                </div>
                                            )}
                                            <Sparklines data={inRateData} limit={120} height={30} margin={1}>
                                                <SparklinesLine color="#4ecdc4" style={{strokeWidth: 1}}/>
                                                <SparklinesReferenceLine type="avg" style={{stroke: '#22c55e', strokeWidth: 1, strokeDasharray: '2,2'}}/>
                                                <SparklinesSpots/>
                                            </Sparklines>
                                        </div>
                                        <div>
                                            {currentRate && (
                                                <div className="px-1 py-1 text-left text-xs">
                                                    <div className="text-blue-300 flex justify-between">
                                                        <span>↑ Out: {formatRateMbps(currentRate.outRateMbps)}</span>
                                                        <span className="text-gray-400">Ø {formatRateMbps(avgOutRate)}</span>
                                                    </div>
{/*                                                    <div className="text-gray-500 text-xs">
                                                        ({formatRate(currentRate.outRate)})
                                                    </div>*/}
                                                </div>
                                            )}
                                            <Sparklines data={outRateData} limit={120} height={30} margin={1}>
                                                <SparklinesLine color="#45b7d1" style={{strokeWidth: 1}}/>
                                                <SparklinesReferenceLine type="avg" style={{stroke: '#3b82f6', strokeWidth: 1, strokeDasharray: '2,2'}}/>
                                                <SparklinesSpots/>
                                            </Sparklines>
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </>
    );
};

export default CounterVisualization;
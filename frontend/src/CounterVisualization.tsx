import React, {useEffect} from "react";
import {Sparklines, SparklinesLine, SparklinesSpots, SparklinesBars} from "react-sparklines";
import {forEach} from "react-bootstrap/ElementChildren";



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
    timestamp?: number;
    counters: Counters;
}

const CounterVisualization: React.FC<CounterVisualizationProps> = ({routerData, selectedNode, selectedLink}) => {

    const [selectedRouterData, setSelectedRouterData] = React.useState<any>(null);
    const [allInterfaceData, setAllInterfaceData] = React.useState<{ [key: string]: InterfaceData }>({});
    const [interfaceHistories, setInterfaceHistories] = React.useState<{ [key: string]: InterfaceData[] }>({});

    useEffect(() => {
        setAllInterfaceData({});
        setInterfaceHistories({});
        setSelectedRouterData(null);
    }, [selectedNode]);

    useEffect(() => {
        if (routerData != null && selectedNode != null) {
            const currentRouterData = routerData[selectedNode];
            setSelectedRouterData(currentRouterData);

            if (currentRouterData) {
                const newAllInterfaceData: { [key: string]: InterfaceData } = {};

                Object.keys(currentRouterData).forEach((interfaceName) => {
                    const interfaceData = currentRouterData[interfaceName];
                    if (interfaceData && interfaceData["openconfig-interfaces:state"] && interfaceData["openconfig-interfaces:state"]["counters"]) {
                        console.log(`Interface: ${interfaceName}, Data:`, interfaceData);

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

                            return prevHistories;
                        });
                    }
                });

                setAllInterfaceData(newAllInterfaceData);
                console.log(newAllInterfaceData)
            }
        }
    }, [routerData, selectedNode, selectedLink]);


    const getInterfaceData = (interfaceName: string, counterType: keyof Counters) => {
        const history = interfaceHistories[interfaceName] || [];
        return history.filter(item => item != null && item.counters).map(item => item.counters[counterType]);
    };

    const interfaceNames = Object.keys(allInterfaceData);

    return (
        <>
            <div
                className="fixed top-4 left-96 z-50 bg-black bg-opacity-75 text-white px-4 py-3 rounded-md text-sm font-mono shadow-lg w-96 max-h-screen overflow-y-auto">
                <div className="font-bold text-xl mt-3 mb-4 text-center">Counter Values</div>

                {selectedNode && (
                    <div className="mb-4 text-center text-sm font-semibold">
                        Node: {selectedNode}
                    </div>
                )}

                {interfaceNames.length === 0 && (
                    <div className="text-center text-gray-400 text-sm">
                        No interface data available
                    </div>
                )}

                {interfaceNames.map((interfaceName) => {
                    const interfaceData = allInterfaceData[interfaceName];
                    const history = interfaceHistories[interfaceName] || [];

                    if (!interfaceData) return null;

                    return (
                        <div key={interfaceName}
                             className="mb-6 border-t border-gray-600 pt-4 first:border-t-0 first:pt-0">
                            <div className="text-sm font-semibold mb-3 text-cyan-400">
                                Interface: {interfaceName}
                            </div>

                            {/* Aktuelle Werte */}
                            <div className="grid grid-cols-2 gap-1 text-xs mb-4 bg-gray-800 p-2 rounded">
                                <div>In Octets: {interfaceData.counters.inOctets.toLocaleString()}</div>
                                <div>Out Octets: {interfaceData.counters.outOctets.toLocaleString()}</div>
                                <div>In Pkts: {interfaceData.counters.inPkts.toLocaleString()}</div>
                                <div>Out Pkts: {interfaceData.counters.outPkts.toLocaleString()}</div>
                                <div>In Errors: {interfaceData.counters.inErrors}</div>
                                <div>Out Errors: {interfaceData.counters.outErrors}</div>
                            </div>

                            {/* Sparklines */}
                            {history.length > 0 && (
                                <div className="space-y-2">
                                    <div>
                                        <div className="text-xs font-semibold mb-1 text-cyan-300">Input Octets</div>
                                        <Sparklines data={getInterfaceData(interfaceName, 'inOctets')} limit={120}
                                                    height={30} margin={1}>
                                            <SparklinesLine color="#00ffff" style={{strokeWidth: 1}}/>
                                            <SparklinesSpots/>
                                        </Sparklines>
                                    </div>

                                    <div>
                                        <div className="text-xs font-semibold mb-1 text-red-300">Output Octets</div>
                                        <Sparklines data={getInterfaceData(interfaceName, 'outOctets')} limit={120}
                                                    height={30} margin={1} showMinMax={true}>
                                            <SparklinesLine color="#ff6b6b" style={{strokeWidth: 1}}/>
                                            <SparklinesSpots/>
                                        </Sparklines>
                                    </div>

                                    <div>
                                        <div className="text-xs font-semibold mb-1 text-green-300">Input Packets</div>
                                        <Sparklines data={getInterfaceData(interfaceName, 'inPkts')} limit={120}
                                                    height={30} margin={1}>
                                            <SparklinesLine color="#4ecdc4" style={{strokeWidth: 1}}/>
                                            <SparklinesSpots/>
                                        </Sparklines>
                                    </div>

                                    <div>
                                        <div className="text-xs font-semibold mb-1 text-blue-300">Output Packets</div>
                                        <Sparklines data={getInterfaceData(interfaceName, 'outPkts')} limit={120}
                                                    height={30} margin={1}>
                                            <SparklinesLine color="#45b7d1" style={{strokeWidth: 1}}/>
                                            <SparklinesSpots/>
                                        </Sparklines>
                                    </div>

                                    {/* Errors nur anzeigen wenn vorhanden */}
                                    {(getInterfaceData(interfaceName, 'inErrors').some(val => val > 0) ||
                                        getInterfaceData(interfaceName, 'outErrors').some(val => val > 0)) && (
                                        <>
                                            <div>
                                                <div className="text-xs font-semibold mb-1 text-orange-300">Input
                                                    Errors
                                                </div>
                                                <Sparklines data={getInterfaceData(interfaceName, 'inErrors')}
                                                            limit={120} height={30} margin={1}>
                                                    <SparklinesLine color="#ff9999"
                                                                    style={{strokeWidth: 1, fill: "none"}}/>
                                                </Sparklines>
                                            </div>

                                            <div>
                                                <div className="text-xs font-semibold mb-1 text-yellow-300">Output
                                                    Errors
                                                </div>
                                                <Sparklines data={getInterfaceData(interfaceName, 'outErrors')}
                                                            limit={120} height={30} margin={1}>
                                                    <SparklinesLine color="#ffcc99"
                                                                    style={{strokeWidth: 1, fill: "none"}}/>
                                                </Sparklines>
                                            </div>
                                        </>
                                    )}

                                    <div className="text-xs opacity-75 text-center">
                                        History: {history.length} entries
                                    </div>
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </>
    )
}

export default CounterVisualization;
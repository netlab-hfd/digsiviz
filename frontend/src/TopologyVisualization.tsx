import React, {useEffect, useRef, useState} from "react";
import {ForceGraph2D} from "react-force-graph";
import {forceCollide, forceLink, forceManyBody, forceSimulation} from 'd3';
import "./index.css";
import io from 'socket.io-client';
import TimeMachine from "./TimeMachine.tsx";
import TimeMachineStats from "./TimeMachineStats.tsx";
import CounterVisualization from "./CounterVisualization.tsx";

interface Node {
    id: string;
    group: string;
    image: string;
    kind: string;
}

interface Link {
    source: string;
    target: string;
    source_interface: string;
    target_interface: string;
}

interface GraphData {
    nodes: Node[];
    links: Link[];
}

interface LinkTrafficRate {
    sourceInRate: number;
    sourceOutRate: number;
    targetInRate: number;
    targetOutRate: number;
    maxRate: number;
    totalRate: number;
}

interface InterfaceHistory {
    timestamp: number;
    inOctets: number;
    outOctets: number;
}

const socket = io('http://127.0.0.1:5000');
const MAX_BANDWIDTH_MBPS = 10; // 10 Mbit/s maximum bandwidth

const TopologyVisualization: React.FC = () => {
    const [routerData, setRouterData] = useState<any>(null);
    const [selectedNode, setSelectedNode] = useState<string | null>(null);
    const [selectedLink, setSelectedLink] = useState<Link | null>(null);
    const [graphData, setGraphData] = useState<GraphData>({nodes: [], links: []});
    const [filter, setFilter] = useState<string>("all");
    const [linkTrafficRates, setLinkTrafficRates] = useState<{ [key: string]: LinkTrafficRate }>({});
    const [interfaceHistories, setInterfaceHistories] = useState<{ [key: string]: InterfaceHistory[] }>({});
    const fgRef = useRef<any>(null);

    const imageCache = useRef<{ [key: string]: HTMLImageElement }>({});

    const getImage = (type: string) => {
        if (imageCache.current[type]) return imageCache.current[type];

        const img = new Image();
        if (type === "r") img.src = "/network-symbols/iRouter.png";
        if (type === "h") img.src = "/network-symbols/iWorkstation.png";
        if (type === "s") img.src = "/network-symbols/iSwitch.png";

        imageCache.current[type] = img;
        return img;
    };

    const getLinkColor = (utilizationPercent: number): string => {
        if (utilizationPercent < 5) {
            return "lightgray";
        } else if (utilizationPercent < 25) {
            return "#22c55e"; // Green
        } else if (utilizationPercent < 50) {
            return "#84cc16"; // Light green
        } else if (utilizationPercent < 75) {
            return "#eab308"; // Yellow
        } else if (utilizationPercent < 90) {
            return "#f97316"; // Orange
        } else {
            return "#ef4444"; // Red
        }
    };

    // Function to calculate traffic rates for an interface
    const calculateInterfaceRates = (nodeId: string, interfaceName: string): { inRate: number, outRate: number } => {
        const historyKey = `${nodeId}-${interfaceName}`;
        const history = interfaceHistories[historyKey] || [];

        if (history.length < 2) return { inRate: 0, outRate: 0 };

        const current = history[history.length - 1];
        const previous = history[history.length - 2];

        const timeDiffSeconds = (current.timestamp - previous.timestamp) / 1000000000; // Nanoseconds to seconds

        if (timeDiffSeconds <= 0) return { inRate: 0, outRate: 0 };

        const inOctetsDiff = Math.max(0, current.inOctets - previous.inOctets);
        const outOctetsDiff = Math.max(0, current.outOctets - previous.outOctets);

        const inRateBps = inOctetsDiff / timeDiffSeconds;
        const outRateBps = outOctetsDiff / timeDiffSeconds;

        const inRateMbps = (inRateBps * 8) / 1000000; // Convert to Mbps
        const outRateMbps = (outRateBps * 8) / 1000000; // Convert to Mbps

        return { inRate: inRateMbps, outRate: outRateMbps };
    };


    const getLinkId = (link: Link): string => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
        const targetId = typeof link.target === 'object' ? link.target.id : link.target;
        return `${sourceId}-${link.source_interface}-${targetId}-${link.target_interface}`;
    };

    const getParallelLinkOffset = (link: any, allLinks: any[]) => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
        const targetId = typeof link.target === 'object' ? link.target.id : link.target;

        const parallelLinks = allLinks.filter(l => {
            const lSourceId = typeof l.source === 'object' ? l.source.id : l.source;
            const lTargetId = typeof l.target === 'object' ? l.target.id : l.target;

            return (lSourceId === sourceId && lTargetId === targetId) ||
                (lSourceId === targetId && lTargetId === sourceId);
        });

        if (parallelLinks.length <= 1) return 0;

        const currentIndex = parallelLinks.findIndex(l => l === link);
        const totalLinks = parallelLinks.length;
        const offsetStep = 25;

        return (currentIndex - (totalLinks - 1) / 2) * offsetStep;
    };

    useEffect(() => {
        socket.on('router_data', (data: { value: string }) => {
            try {
                const parsedData = JSON.parse(data.value);
                setRouterData(parsedData);
            } catch (error) {
                console.error("Fehler beim Parsen der WebSocket-Daten:", error);
            }
        });

        return () => {
            socket.off('router_data');
        };
    }, []);

    useEffect(() => {
        fetch("http://127.0.0.1:5000/topology", {headers: {'Access-Control-Allow-Origin': '*'}})
            .then(response => response.json())
            .then(data => setGraphData(data))
            .catch(error => console.error("Fehler beim Laden der Topologie:", error));
    }, []);

    useEffect(() => {
        if (!routerData) return;

        setInterfaceHistories(prevHistories => {
            const newHistories = { ...prevHistories };

            Object.keys(routerData).forEach(nodeId => {
                const nodeData = routerData[nodeId];
                if (!nodeData) return;

                Object.keys(nodeData).forEach(interfaceName => {
                    const interfaceData = nodeData[interfaceName];
                    if (interfaceData &&
                        interfaceData["openconfig-interfaces:state"] &&
                        interfaceData["openconfig-interfaces:state"]["counters"]) {

                        const historyKey = `${nodeId}-${interfaceName}`;
                        const currentHistory = newHistories[historyKey] || [];

                        const newEntry: InterfaceHistory = {
                            timestamp: interfaceData["timestamp"] || Date.now(),
                            inOctets: interfaceData["openconfig-interfaces:state"]["counters"]["in-octets"] || 0,
                            outOctets: interfaceData["openconfig-interfaces:state"]["counters"]["out-octets"] || 0
                        };

                        const updatedHistory = [...currentHistory, newEntry];
                        const limitedHistory = updatedHistory.length > 120 ?
                            updatedHistory.slice(updatedHistory.length - 120) : updatedHistory;

                        newHistories[historyKey] = limitedHistory;
                    }
                });
            });

            return newHistories;
        });
    }, [routerData]);

    useEffect(() => {
        if (!routerData || !graphData.links.length) return;

        const newLinkTrafficRates: { [key: string]: LinkTrafficRate } = {};

        graphData.links.forEach(link => {
            const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
            const targetId = typeof link.target === 'object' ? link.target.id : link.target;

            const sourceRates = calculateInterfaceRates(sourceId, link.source_interface);
            const targetRates = calculateInterfaceRates(targetId, link.target_interface);

            const allRates = [sourceRates.inRate, sourceRates.outRate, targetRates.inRate, targetRates.outRate];
            const maxRate = Math.max(...allRates);
            const totalRate = allRates.reduce((sum, rate) => sum + rate, 0);

            const linkId = getLinkId(link);
            newLinkTrafficRates[linkId] = {
                sourceInRate: sourceRates.inRate,
                sourceOutRate: sourceRates.outRate,
                targetInRate: targetRates.inRate,
                targetOutRate: targetRates.outRate,
                maxRate,
                totalRate
            };
        });

        setLinkTrafficRates(newLinkTrafficRates);
    }, [interfaceHistories, graphData.links, routerData]);

    useEffect(() => {
        fgRef.current.d3Force('charge', forceManyBody().strength(-300));
        fgRef.current.d3Force('link', forceLink().distance(90));
        fgRef.current.d3Force('collision', forceCollide(30));

        setTimeout(() => {
            fgRef.current.zoom(2);
            fgRef.current.centerAt(0, 0);
        }, 300);
    }, [graphData]);

    const handleNodeClick = (node: any) => {
        setSelectedNode(node.id);
        setSelectedLink(null);
    };

    const handleLinkClick = (link: any) => {
        setSelectedLink(link);
        setSelectedNode(null);
    };

    const renderData = (data: any) => {
        if (!data) return <p>Keine Daten verfügbar.</p>;

        if (typeof data === 'object' && !Array.isArray(data)) {
            return (
                <ul className="ml-4">
                    {Object.entries(data).map(([key, value]) => (
                        <li key={key} className="border p-2 rounded mb-1">
                            <strong>{key}:</strong> {renderData(value)}
                        </li>
                    ))}
                </ul>
            );
        } else if (Array.isArray(data)) {
            return (
                <ul>
                    {data.map((item, index) => (
                        <li key={index}>{renderData(item)}</li>
                    ))}
                </ul>
            );
        } else {
            return <span>{String(data)}</span>;
        }
    };

    const filteredData = () => {
        if (!routerData) return <p>Warte auf Daten...</p>;

        const applyFilter = (data: any, routerData: any, interfaceName?: string) => {
            if (filter === "all") return data;

            let filteredData = Object.entries(data)
                .map(([key, value]) => {
                    if (typeof value === "object") {
                        const filteredInterfaceData = Object.keys(value)
                            .filter(subKey => subKey.includes(filter))
                            .reduce((obj, subKey) => {
                                obj[subKey] = value[subKey];
                                return obj;
                            }, {} as any);

                        return Object.keys(filteredInterfaceData).length > 0
                            ? {[key]: filteredInterfaceData}
                            : null;
                    }
                    return null;
                })
                .filter(Boolean)

            let mergedStatistics = {};

            if (filter === "statistics") {
                const baseStatistics = data.statistics || {};
                const ethernetStatistics = data.ethernet?.statistics || {};

                mergedStatistics = {...baseStatistics, ...ethernetStatistics};

                if (Object.keys(mergedStatistics).length > 0) {
                    filteredData.push({statistics: mergedStatistics});
                }
            }

            if (data[filter]) {
                filteredData.push({[filter]: data[filter]});
            }

            if (filteredData.length > 0) {
                return Object.assign({}, ...filteredData);
            }

            if (interfaceName && routerData[interfaceName] && routerData[interfaceName][filter]) {
                return {[filter]: routerData[interfaceName][filter]};
            }

            return {"Keine Daten gefunden für Filter": ""};
        };

        if (selectedNode) {
            console.log("Node geklickt:", selectedNode);
            const nodeData = routerData[selectedNode];

            if (!nodeData) return <p>Keine Daten für {selectedNode} gefunden.</p>;

            return renderData(applyFilter(nodeData, routerData[selectedNode]));
        }

        if (selectedLink) {
            const {source, target, source_interface, target_interface} = selectedLink;

            console.log("Link geklickt:", selectedLink);

            const sourceId = typeof source === 'object' ? source.id : source;
            const targetId = typeof target === 'object' ? target.id : target;

            console.log("Source-ID:", sourceId);
            console.log("Target-ID:", targetId);

            console.log("Router-Keys:", Object.keys(routerData));

            const sourceRouterData = routerData[sourceId] || null;
            const targetRouterData = routerData[targetId] || null;

            console.log("Source Router:", sourceRouterData);
            console.log("Target Router:", targetRouterData);

            if (!sourceRouterData) {
                return <p>Keine Daten für {sourceId} gefunden.</p>;
            }

            const sourceInterfaceData = sourceRouterData[source_interface] || sourceRouterData || null;
            const targetInterfaceData = targetRouterData ? (targetRouterData[target_interface] || targetRouterData) : null;

            console.log("Source Interface:", sourceInterfaceData);
            console.log("Target Interface:", targetInterfaceData);

            return (
                <>
                    <h4>Interface von {sourceId}: {source_interface}</h4>
                    {sourceInterfaceData ? renderData(applyFilter(sourceInterfaceData, sourceRouterData, source_interface)) :
                        <p>Keine Daten für {source_interface}.</p>}

                    {targetInterfaceData && (
                        <>
                            <hr/>
                            <h4>Interface von {targetId}: {target_interface}</h4>
                            {renderData(applyFilter(targetInterfaceData, targetRouterData, target_interface))}
                        </>
                    )}
                </>
            );
        }

        return <p>Wähle einen Node oder Link aus.</p>;
    };

    return (
        <div className="flex flex-col h-full w-screen">
            {
                selectedNode ?
                    <div>
                        <CounterVisualization routerData={routerData} selectedNode={"r1"}
                                              selectedLink={selectedLink}/>
                        <CounterVisualization routerData={routerData} selectedNode={"r2"}
                                              selectedLink={selectedLink}/>
                        <CounterVisualization routerData={routerData} selectedNode={"r3"}
                                              selectedLink={selectedLink}/>
                        <CounterVisualization routerData={routerData} selectedNode={"r4"}
                                              selectedLink={selectedLink}/>
                        <CounterVisualization routerData={routerData} selectedNode={"r5"}
                                              selectedLink={selectedLink}/>
                    </div>
                    : <div/>
            }

            {
                selectedLink ?
                    <div>
                        <CounterVisualization routerData={routerData} selectedNode={selectedLink.source.id}
                                              selectedLink={selectedLink}/>
                        <CounterVisualization routerData={routerData} selectedNode={selectedLink.target.id}
                                              selectedLink={selectedLink}/>
                    </div> : <div/>
            }

            <TimeMachineStats/>
            <div className="container-fluid d-flex p-0 h-screen">
                <div className="row flex-grow-1 m-0 h-full">
                    {/* Linke Spalte (Echtzeit-Infos)*/}
                    <div className="col-4  overflow-hidden bg-light h-full">
                        <TimeMachine/>
                        <div className="p-2 overflow-auto bg-light h-full">
                            <h1>
                                {selectedNode
                                    ? selectedNode
                                    : selectedLink
                                        ? `${selectedLink.source?.id || "???"} <-> ${selectedLink.target?.id || "???"}`
                                        : ""}
                            </h1>

                            <label>Filter: </label>
                            <select className="form-select mb-2" value={filter}
                                    onChange={(e) => setFilter(e.target.value)}>
                                <option value="all">Alle Daten</option>
                                <option value="statistics">Statistiken</option>
                                <option value="traffic-rate">Datenrate</option>
                                <option value="transceiver">Transceiver</option>
                            </select>
                            {filteredData()}
                        </div>
                    </div>
                    {/* Rechte Spalte (ForceGraph) */}
                    <div className="col-8 p-2 h-screen overflow-hidden">
                        <ForceGraph2D
                            width={window.innerWidth * 0.66}
                            height={window.innerHeight * 0.9}
                            ref={fgRef}
                            graphData={graphData}
                            nodeAutoColorBy="group"
                            nodeLabel={(node) => `
                             <div>
                                <strong>Node: ${node.id}</strong></br>
                                Kind: ${node.kind}</br>
                                Image: ${node.image}</br>
                            </div>
                            `}
                            nodeCanvasObject={(node, ctx, globalScale) => {
                                const fontSize = 16 / globalScale;
                                ctx.font = `${fontSize}px Sans-Serif`;
                                ctx.textAlign = "center";
                                ctx.textBaseline = "middle";

                                ctx.fillStyle = "gray";
                                ctx.fillText(node.kind, node.x, node.y + 10);

                                // Bild für Knoten
                                const type = node.id.substring(0, 1);
                                const img = getImage(type);

                                const size = 12;

                                ctx.drawImage(img, node.x - size / 2, node.y - size / 2, size, size);

                                ctx.fillStyle = "black";
                                ctx.fillText(node.id, node.x, node.y - 10);
                            }}
                            nodeCanvasObjectMode={() => 'after'}
                            linkCanvasObject={(link, ctx, globalScale) => {
                                const source = link.source as { x: number; y: number };
                                const target = link.target as { x: number; y: number };

                                const linkId = getLinkId(link);
                                const linkTraffic = linkTrafficRates[linkId];
                                const utilizationPercent = linkTraffic ?
                                    (linkTraffic.maxRate / MAX_BANDWIDTH_MBPS) * 100 : 0;

                                const linkColor = getLinkColor(utilizationPercent);
                                const lineWidth = utilizationPercent > 5 ?
                                    Math.min(4, 1 + (utilizationPercent / 25)) : 1;

                                const offset = getParallelLinkOffset(link, graphData.links);
                                if (offset === 0) {
                                    ctx.beginPath();
                                    ctx.moveTo(source.x, source.y);
                                    ctx.lineTo(target.x, target.y);
                                    ctx.strokeStyle = linkColor;
                                    ctx.lineWidth = lineWidth;
                                    ctx.stroke();

                                    const midX = (source.x + target.x) / 2;
                                    const midY = (source.y + target.y) / 2;

                                    const fontSize = 15 / globalScale;
                                    ctx.font = `${fontSize}px Sans-Serif`;
                                    ctx.fillStyle = "blue";
                                    ctx.textAlign = "center";
                                    ctx.textBaseline = "middle";

                                    const text = `${link.source?.id}/${link.source_interface}<->${link.target?.id}/${link.target_interface}`;
                                    const textWidth = ctx.measureText(text).width;
                                    ctx.fillStyle = "white";
                                    ctx.fillRect(midX - textWidth/2 - 2, midY - fontSize/2 - 1, textWidth + 4, fontSize + 2);

                                    ctx.fillStyle = "blue";
                                    ctx.fillText(text, midX, midY);
                                } else {
                                    const dx = target.x - source.x;
                                    const dy = target.y - source.y;
                                    const distance = Math.sqrt(dx * dx + dy * dy);

                                    const normalX = -dy / distance * offset;
                                    const normalY = dx / distance * offset;

                                    const controlX = (source.x + target.x) / 2 + normalX;
                                    const controlY = (source.y + target.y) / 2 + normalY;

                                    ctx.beginPath();
                                    ctx.moveTo(source.x, source.y);
                                    ctx.quadraticCurveTo(controlX, controlY, target.x, target.y);
                                    ctx.strokeStyle = linkColor;
                                    ctx.lineWidth = lineWidth;
                                    ctx.stroke();

                                    const midX = (source.x + target.x) / 2 + normalX * 0.7;
                                    const midY = (source.y + target.y) / 2 + normalY * 0.7;

                                    const fontSize = 15 / globalScale;
                                    ctx.font = `${fontSize}px Sans-Serif`;
                                    ctx.fillStyle = "blue";
                                    ctx.textAlign = "center";
                                    ctx.textBaseline = "middle";

                                    const text = `${link.source?.id}/${link.source_interface}<->${link.target?.id}/${link.target_interface}`;
                                    const textWidth = ctx.measureText(text).width;
                                    ctx.fillStyle = "white";
                                    ctx.fillRect(midX - textWidth/2 - 2, midY - fontSize/2 - 1, textWidth + 4, fontSize + 2);

                                    ctx.fillStyle = "blue";
                                    ctx.fillText(text, midX, midY);
                                }
                            }}
                            onNodeClick={handleNodeClick}
                            onLinkClick={handleLinkClick}
                        />
                    </div>
                </div>
            </div>
        </div>
    );
};

export default TopologyVisualization;
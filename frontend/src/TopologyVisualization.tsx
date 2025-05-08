import React, {useEffect, useRef, useState} from "react";
import {ForceGraph2D} from "react-force-graph";
import {forceCollide, forceLink, forceManyBody} from 'd3';
import "./index.css";
import io from 'socket.io-client';
import TimeMachine from "./TimeMachine.tsx";

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

const socket = io('http://127.0.0.1:5000');

const TopologyVisualization: React.FC = () => {
    const [routerData, setRouterData] = useState<any>(null);
    const [selectedNode, setSelectedNode] = useState<string | null>(null);
    const [selectedLink, setSelectedLink] = useState<Link | null>(null);
    const [graphData, setGraphData] = useState<GraphData>({nodes: [], links: []});
    const [filter, setFilter] = useState<string>("all");
    const fgRef = useRef<any>(null);

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
        fgRef.current.d3Force('charge', forceManyBody().strength(-300));
        fgRef.current.d3Force('link', forceLink().distance(90));
        fgRef.current.d3Force('collision', forceCollide(30));

        setTimeout(() => {
            fgRef.current.zoom(2);
            fgRef.current.centerAt(0, 0);
        }, 300);
    }, []);

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

            <div className="container-fluid d-flex p-0 h-screen">
                <div className="row flex-grow-1 m-0 h-full">
                    {/* Linke Spalte (Echtzeit-Infos)*/}
                    <div className="col-4  overflow-hidden bg-light h-full">
                        <TimeMachine/>
                    <div className="p-2 overflow-auto bg-light h-full" >
                        <h1>
                            {selectedNode
                                ? selectedNode
                                : selectedLink
                                    ? `${selectedLink.source?.id || "???"} <-> ${selectedLink.target?.id || "???"}`
                                    : ""}
                        </h1>

                        <label>Filter: </label>
                        <select className="form-select mb-2" value={filter} onChange={(e) => setFilter(e.target.value)}>
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
                                const fontSize = 11 / globalScale;
                                ctx.font = `${fontSize}px Sans-Serif`;
                                ctx.textAlign = "center";
                                ctx.textBaseline = "middle";

                                ctx.fillStyle = "gray";
                                ctx.fillText(node.kind, node.x, node.y + 10);

                                // Bild für Knoten
                                const img = new Image();
                                if (node.id.substring(0, 1) == "r") {
                                    img.src = "/network-symbols/iRouter.png"
                                }
                                if (node.id.substring(0, 1) == "h") {
                                    img.src = "/network-symbols/iWorkstation.png"
                                }
                                if (node.id.substring(0, 1) == "s") {
                                    img.src = "/network-symbols/iSwitch.png"
                                }

                                const size = 12;

                                ctx.drawImage(img, node.x - size / 2, node.y - size / 2, size, size)

                                ctx.fillStyle = "black";
                                ctx.fillText(node.id, node.x, node.y - 10);
                            }}
                            nodeCanvasObjectMode={() => 'after'}
                            linkCanvasObject={(link, ctx, globalScale) => {
                                const source = link.source as { x: number; y: number };
                                const target = link.target as { x: number; y: number };

                                ctx.beginPath();
                                ctx.moveTo(source.x, source.y);
                                ctx.lineTo(target.x, target.y);
                                ctx.strokeStyle = "lightgray";
                                ctx.lineWidth = 1;
                                ctx.stroke();

                                const midX = (source.x + target.x) / 2;
                                const midY = (source.y + target.y) / 2;

                                const fontSize = 10 / globalScale;
                                ctx.font = `${fontSize}px Sans-Serif`;
                                ctx.fillStyle = "blue";
                                ctx.textAlign = "center";
                                ctx.textBaseline = "middle";
                                ctx.fillText(`${link.source_interface} -> ${link.target_interface}`, midX, midY);
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

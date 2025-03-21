import React, { useEffect, useState } from 'react';
import io from 'socket.io-client';

const socket = io('http://localhost:5000');

const WebSocketComponent: React.FC = () => {
    const [routerData, setRouterData] = useState<any>(null);

    useEffect(() => {
        socket.on('router_data', (data: { value: string }) => {
            try {
                const parsedData = JSON.parse(data.value);
                console.log("Empfangene Router-Daten:", parsedData);
                setRouterData(parsedData);
            } catch (error) {
                console.error("Fehler beim Parsen der WebSocket-Daten:", error);
            }
        });

        return () => {
            socket.off('router_data');
        };
    }, []);

    const renderJson = (data: any): JSX.Element => {
        if (typeof data === 'object' && data !== null) {
            return (
                <ul className="ml-4">
                    {Object.entries(data).map(([key, value]) => (
                        <li key={key} className="border p-2 rounded mb-1">
                            <strong>{key}:</strong> {renderJson(value)}
                        </li>
                    ))}
                </ul>
            );
        } else if (Array.isArray(data)) {
            return (
                <ul>
                    {data.map((item, index) => (
                        <li key={index}>{renderJson(item)}</li>
                    ))}
                </ul>
            );
        } else {
            return <span>{String(data)}</span>;
        }
    };

    return (
        <div className="p-4 w-50 mx-auto h-full ">
            <h1 className="text-2xl font-bold mb-4">Live Router-Status</h1>
            {routerData ? (
                <div>
                    <h2 className="text-xl font-semibold">Empfangene Daten</h2>
                    {Object.keys(routerData).length > 0 ? (
                        Object.entries(routerData).map(([router, interfaces]) => (
                            <div key={router} className="border rounded p-4 mb-4">
                                <h3 className="text-lg font-semibold">Router: {router}</h3>
                                <div>{renderJson(interfaces)}</div>
                            </div>
                        ))
                    ) : (
                        <p>Keine Daten verfügbar.</p>
                    )}
                </div>
            ) : (
                <p>Warte auf Daten...</p>
            )}
        </div>
    );
};

export default WebSocketComponent;

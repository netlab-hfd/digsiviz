import { useEffect, useState } from "react";
import "bootstrap/dist/css/bootstrap.min.css";

type Container = {
    container_id: string;
    name: string;
    ipv4_address?: string;
    ipv6_address?: string;
    state: string;
    group?: string;
    image?: string;
    kind?: string;
    lab_name?: string;
    [key: string]: any;
};

const ClabInfo: React.FC = () => {
    const [clabData, setClabData] = useState<Container[]>([]);

    useEffect(() => {
        fetch("http://127.0.0.1:5000/clab-info")
            .then((response) => response.json())
            .then((data) => {
                setClabData(data.containers || []);
            })
            .catch((error) => console.error("Fehler beim Laden der Topologie:", error));
    }, []);

    return (
        <div className="container py-4 h-full">
            {clabData.length === 0 ? (
                <p className="text-center">Lade Container-Daten...</p>
            ) : (
                <div className="row">
                    {clabData.map((container) => (
                        <div key={container.container_id} className="col-md-6 col-lg-4 mb-4">
                            <div className="card shadow-sm p-3">
                                <h5 className="card-title">{container.name}</h5>
                                <div className="card-body">
                                    {Object.entries(container).map(([key, value]) => (
                                        <div key={key} className="d-flex justify-content-between border-bottom py-1">
                                            <span className="fw-bold">{key}:</span>
                                            <span>{String(value)}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default ClabInfo;

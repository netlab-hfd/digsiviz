import WebSocketComponent from "./WebSocketComponent.tsx";
import TopologyVisualization from "./TopologyVisualization.tsx";
import AppNavbar from "./AppNavbar.tsx";
import {Route, Routes} from "react-router-dom";
import ClabInfo from './ClabInfo.tsx';


const App: React.FC = () => {

    return (
        <div className="h-screen flex flex-col">
            <AppNavbar />
            <div className="flex-grow flex flex-col overflow-y-auto items-center text-center justify-center">
                <Routes>
                    <Route path="/" element={<h1>Start</h1>} />
                    <Route path="/websocket" element={<WebSocketComponent />} />
                    <Route path="/topology" element={<TopologyVisualization />} />
                    <Route path="/clabinfo" element={<ClabInfo />} />
                </Routes>
            </div>
        </div>
    );



}

export default App

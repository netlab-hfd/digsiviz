import statistics
from flask_socketio import SocketIO

class Statistics:
    socketio = None

    def __init__(self, socketio: SocketIO):
        super().__init__()
        self.socketio = socketio

    def calculate_timestamp_deviation(self, general_timestamp, router_data):
        timestamps = []
        for router_name, interfaces in router_data.items():
            for interface_name, data in interfaces.items():
                timestamp = data.get("timestamp")
                timestamps.append(timestamp)

        self.socketio.emit('timemachine_stats', {'deviation': statistics.stdev(timestamps)}) 

        

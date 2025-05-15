import statistics
from flask_socketio import SocketIO

class Statistics:
    socketio = None

    def __init__(self, socketio: SocketIO):
        super().__init__()
        self.socketio = socketio

    def send_statistics(self, general_timestamp, router_data, cycle_starttime=None, poll_duration=None):
        router_timestamp_deviation = self.calculate_router_timestamp_deviation(general_timestamp, router_data)
        min_timestamp = self.get_min_timestamp(router_data)

        cycle_duration_ms = (general_timestamp - cycle_starttime) * 1000 if cycle_starttime else None

        self.socketio.emit('timemachine_stats', {
            'deviation': router_timestamp_deviation,
            'min_timestamp': min_timestamp,
            'cycle_starttime': cycle_starttime,
            'general_timestamp': general_timestamp,
            'cycle_duration_ms': cycle_duration_ms,
            'poll_duration': poll_duration
        })

    

    def calculate_router_timestamp_deviation(self, general_timestamp, router_data):
        timestamps = []
        for router_name, interfaces in router_data.items():
            for interface_name, data in interfaces.items():
                timestamp = data.get("timestamp")
                timestamps.append(timestamp)

        if len(timestamps) >= 1:
            return statistics.stdev(timestamps)
        
        return 0.0
    
    def get_min_timestamp(self, router_data):
        min_timestamp = None
        for router_name, interfaces in router_data.items():
            for interface_name, data in interfaces.items():
                timestamp = data.get("timestamp")
                if min_timestamp is None or (timestamp is not None and timestamp < min_timestamp):
                    min_timestamp = timestamp
        return min_timestamp

        

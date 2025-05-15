import statistics
from flask_socketio import SocketIO

class Statistics:
    socketio = None

    def __init__(self, socketio: SocketIO):
        super().__init__()
        self.socketio = socketio

    def send_statistics(self, general_timestamp, router_data, cycle_starttime=None, poll_duration=None):
        general_timestamp_ms = general_timestamp * 1000 if general_timestamp else None
        cycle_starttime_ms = cycle_starttime * 1000 if cycle_starttime else None

        poll_duration_ms = poll_duration * 1000 if poll_duration is not None else None

        router_timestamp_deviation_ms = self.calculate_router_timestamp_deviation(router_data)
        min_timestamp_ms = self.get_min_timestamp(router_data)

        cycle_duration_ms = (general_timestamp - cycle_starttime) * 1000 if cycle_starttime else None

        self.socketio.emit('timemachine_stats', {
            'deviation_ms': router_timestamp_deviation_ms,
            'min_timestamp_ms': min_timestamp_ms,
            'cycle_starttime_ms': cycle_starttime_ms,
            'general_timestamp_ms': general_timestamp_ms,
            'cycle_duration_ms': cycle_duration_ms,
            'poll_duration_ms': poll_duration_ms
        })

    def calculate_router_timestamp_deviation(self, router_data):
        timestamps = []
        for router_name, interfaces in router_data.items():
            for interface_name, data in interfaces.items():
                timestamp_ns = data.get("timestamp")
                if timestamp_ns is not None:

                    timestamp_ms = timestamp_ns / 1_000_000
                    timestamps.append(timestamp_ms)

        if len(timestamps) >= 2:
            return statistics.stdev(timestamps)
        
        return 0.0
    
    def get_min_timestamp(self, router_data):
        min_timestamp_ms = None
        for router_name, interfaces in router_data.items():
            for interface_name, data in interfaces.items():
                timestamp_ns = data.get("timestamp")
                if timestamp_ns is not None:
                    timestamp_ms = timestamp_ns / 1_000_000
                    if min_timestamp_ms is None or timestamp_ms < min_timestamp_ms:
                        min_timestamp_ms = timestamp_ms
        return min_timestamp_ms

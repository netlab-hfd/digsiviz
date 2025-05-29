import statistics
from flask_socketio import SocketIO
import json

class Statistics:
    socketio = None

    def __init__(self):
        super().__init__()


    def calc_statistics(self, hostname, gnmi_data_collection_timestamp, collected_timestamps, gnmi_polling_duration=None):
        gnmi_polling_duration_ms = gnmi_polling_duration * 1000 if gnmi_polling_duration is not None else None

        router_timestamp_deviation_ms = self.calculate_router_timestamp_deviation(collected_timestamps)
        min_router_timestamp_ms = self.get_min_router_timestamp(collected_timestamps)

        stats = {
            'timestamp': gnmi_data_collection_timestamp,
            'hostname': hostname,
            'router_timestamp_deviation_ms': router_timestamp_deviation_ms,
            'min_router_timestamp_ms': min_router_timestamp_ms,
            'gnmi_polling_duration_ms': gnmi_polling_duration_ms
        }

        return stats

    def calculate_router_timestamp_deviation(self, collected_timestamps):
        timestamps = []
        for timestamp in collected_timestamps:
            timestamp_ms = timestamp / 1_000_000
            timestamps.append(timestamp_ms)

        if len(timestamps) >= 2:
            return statistics.stdev(timestamps)
        
        return 0.0
    
    def get_min_router_timestamp(self, collected_timestamps):
        min_timestamp_ms = None
        for timestamp in collected_timestamps:
                timestamp_ms = timestamp / 1_000_000
                if min_timestamp_ms is None or timestamp_ms < min_timestamp_ms:
                    min_timestamp_ms = timestamp_ms

        return min_timestamp_ms
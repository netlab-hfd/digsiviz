import statistics
from flask_socketio import SocketIO

class Statistics:
    socketio = None

    def __init__(self, socketio: SocketIO):
        super().__init__()
        self.socketio = socketio

    def send_statistics(self, gnmi_data_collection_timestamp, router_data, datapolling_cycle_starttime=None, gnmi_polling_duration=None):
        gnmi_data_collection_timestamp_ms = gnmi_data_collection_timestamp * 1000 if gnmi_data_collection_timestamp else None
        datapolling_cycle_starttime_ms = datapolling_cycle_starttime * 1000 if datapolling_cycle_starttime else None

        gnmi_polling_duration_ms = gnmi_polling_duration * 1000 if gnmi_polling_duration is not None else None

        router_timestamp_deviation_ms = self.calculate_router_timestamp_deviation(router_data)
        min_router_timestamp_ms = self.get_min_router_timestamp(router_data)

        datapolling_cycle_duration_ms = (gnmi_data_collection_timestamp_ms - datapolling_cycle_starttime_ms) if datapolling_cycle_starttime_ms else None


        self.socketio.emit('timemachine_stats', {
            'router_timestamp_deviation_ms': router_timestamp_deviation_ms,
            'min_router_timestamp_ms': min_router_timestamp_ms,
            'datapolling_cycle_starttime_ms': datapolling_cycle_starttime_ms,
            'gnmi_data_collection_timestamp_ms': gnmi_data_collection_timestamp_ms,
            'datapolling_cycle_duration_ms': datapolling_cycle_duration_ms,
            'gnmi_polling_duration_ms': gnmi_polling_duration_ms
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
    
    def get_min_router_timestamp(self, router_data):
        min_timestamp_ms = None
        for router_name, interfaces in router_data.items():
            for interface_name, data in interfaces.items():
                timestamp_ns = data.get("timestamp")
                if timestamp_ns is not None:
                    timestamp_ms = timestamp_ns / 1_000_000
                    if min_timestamp_ms is None or timestamp_ms < min_timestamp_ms:
                        min_timestamp_ms = timestamp_ms
        return min_timestamp_ms

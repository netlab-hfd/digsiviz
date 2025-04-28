from flask_socketio import SocketIO
import json
import time
from collections import deque
import threading
from modules.gnmiclient import GnmiClient

class TimeMachine():



    time_machine_deque = deque(maxlen=120)
    time_machine_lock = threading.Lock()
    time_machine_state = {
    'timestamp': None,
    'active': False
    }


    def __init__(self, socketio: SocketIO, gnmiclient: GnmiClient):
        super().__init__()
        self.socketio = socketio
        self.gnmiclient = gnmiclient


    def time_machine(self):
        with self.time_machine_lock:
            start_time = time.time()
            data = self.gnmiclient.get_structured_data_parallel()
            timestamp_utc = time.time()
            self.time_machine_deque.append((timestamp_utc, data))

            elapsed_time = time.time() - start_time
            sleep_time = max(0.5 - elapsed_time, 0)

            print(f"(TOTAL)Elapsed time fetching gNMI data: {elapsed_time} seconds")
            print(f"(TOTAL)Sleeping for: {sleep_time} seconds")

            time.sleep(sleep_time)

            return self.time_machine_deque[-1]
        
    def get_router_values(self):
        while True:
            try:
                if not self.time_machine_state['active'] and self.time_machine_state['timestamp'] is None:
                    current_timestamp, response = self.time_machine()
                    available_timestamps = [entry[0] for entry in self.time_machine_deque]
                    self.socketio.emit('router_data', {'value': json.dumps(response)})
                    self.socketio.emit('available_timestamps', {'values': available_timestamps})

                else:
                    target_timestamp = self.time_machine_state['timestamp'] or self.time_machine_deque[-1][0]
                
                    print(f"Time Machine activated, Timestamp: {target_timestamp}")

                    try:
                        index = next(i for i, entry in enumerate(self.time_machine_deque) if entry[0] == target_timestamp)
                        history_values = self.time_machine_deque[index][1]
                        available_timestamps = [entry[0] for entry in self.time_machine_deque]

                        self.socketio.emit('router_data', {'value': json.dumps(history_values)})
                        self.socketio.emit('available_timestamps', {'values': available_timestamps})

                    except StopIteration:
                        print(f"No matching timestamp found for {target_timestamp}")

                    time.sleep(0.5)
            except Exception as e:
                print(f"Error in get_router_values: {e}")
                self.socketio.emit('error', {'message': str(e)})
                time.sleep(1) 


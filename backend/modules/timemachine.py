from flask_socketio import SocketIO
import json
import time
from collections import deque
import threading
from modules.gnmiclient import GnmiClient
from modules.enum.timemachine_mode import Gnmi_Mode
from modules.statistics import Statistics
import copy

class TimeMachine():
    """
    Stores gNMI data that were fetched by GnmiClient object
    """

    time_machine_deque = deque(maxlen=120)
    time_machine_lock = threading.Lock()
    time_machine_state = {
    'timestamp': None,
    'active': False
    }

    time_machine_deque_copy = None

    def __init__(self, socketio: SocketIO, gnmiclient: GnmiClient, gnmimode : Gnmi_Mode = Gnmi_Mode.GET_PARALLEL):
        super().__init__()
        self.socketio = socketio
        self.gnmiclient = gnmiclient
        self.gnmimode = gnmimode
        self.stats = Statistics(self.socketio)


    def time_machine(self,  mode: Gnmi_Mode = Gnmi_Mode.GET_PARALLEL):
        """
        Uses GnmiClient to retrieve data and stores it with an unique time stamp to a deque. Returns the last value of the deque (current value).
        """
        with self.time_machine_lock:
            start_time = time.time()

            if(mode == Gnmi_Mode.GET_SERIAL):
                data = self.gnmiclient.get_structured_data_serial()

            if(mode == Gnmi_Mode.GET_PARALLEL):
                data = self.gnmiclient.get_structured_data_parallel()

            if(mode == Gnmi_Mode.SUBSCRIBE_ON_CHANGE):
                if self.gnmiclient.subscription_data is None:
                    self.gnmiclient.subscribe_gnmi_data()

                data = self.gnmiclient.subscription_data


            timestamp_utc = time.time()

            if (mode == Gnmi_Mode.SUBSCRIBE_ON_CHANGE):
                self.time_machine_deque.append((timestamp_utc, copy.deepcopy(data)))
            else:
                self.time_machine_deque.append((timestamp_utc, data))

            elapsed_time = time.time() - start_time
            sleep_time = max(0.5 - elapsed_time, 0)

            print(f"(TOTAL)Elapsed time fetching gNMI data: {elapsed_time} seconds")
            print(f"(TOTAL)Sleeping for: {sleep_time} seconds")

            time.sleep(sleep_time)

            return elapsed_time, self.time_machine_deque[-1]
        
    def get_router_values(self):
        """
        Controls the time machine functionality depending on the currently set mode (current value or historical value). Emits the value through web socket.
        """
        while True:
            try:
                if not self.time_machine_state['active'] and self.time_machine_state['timestamp'] is None:
                    cycle_starttime = time.time()
                    polling_elapsed_time, (current_timestamp, response) = self.time_machine(self.gnmimode)
                    available_timestamps = [entry[0] for entry in self.time_machine_deque]
                    self.socketio.emit('router_data', {'value': json.dumps(response)})
                    self.socketio.emit('available_timestamps', {'values': available_timestamps})
                    self.stats.send_statistics(current_timestamp,response, cycle_starttime, polling_elapsed_time)
                    self.time_machine_deque_copy = copy.deepcopy(self.time_machine_deque)

                else:
                    target_timestamp = self.time_machine_state['timestamp'] or self.time_machine_deque[-1][0]
                
                    print(f"Time Machine activated, Timestamp: {target_timestamp}")
                    

                    try:
                        index = next(i for i, entry in enumerate(self.time_machine_deque) if entry[0] == target_timestamp)
                        history_values = self.time_machine_deque_copy[index][1]
                        available_timestamps = [entry[0] for entry in self.time_machine_deque_copy]

                        self.stats.send_statistics(self.time_machine_deque_copy[index][0],history_values)
                        
                        self.socketio.emit('router_data', {'value': json.dumps(history_values)})
                        self.socketio.emit('available_timestamps', {'values': available_timestamps})

                    except StopIteration:
                        print(f"No matching timestamp found for {target_timestamp}")

                    time.sleep(1)
            except Exception as e:
                print(f"Error in get_router_values: {e}")
                self.socketio.emit('error', {'message': str(e)})
                time.sleep(1) 


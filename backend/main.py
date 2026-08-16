from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS

from modules.yamlinterpreter import YamlInterpreter
from modules.clabassistant import ClabAssistant
from modules.gnmiclient import GnmiClient
from modules.timemachine import TimeMachine
import threading

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*")

yamlinterpreter = YamlInterpreter(filepath="ma-fp-stumpf.clab.yml")
clabassistant = ClabAssistant()
gnmiclient = GnmiClient(yamlinterpreter=yamlinterpreter, clabassistant=clabassistant)
timemachine = TimeMachine(socketio=socketio, gnmiclient=gnmiclient)

topology = yamlinterpreter.topology_graph


threading.Thread(target=timemachine.get_router_values, daemon=True).start()


@app.route("/topology", methods=["GET"])
def topology():
    return yamlinterpreter.topology_graph

@app.route("/clab-info", methods=["GET"])
def clab_info():
    return clabassistant.load_clab_info()

@socketio.on('connect')
def handle_connect():
    # NOTE: this condition checks whether the *time machine* is active, not
    # whether a poller is already running, so it does not prevent a second
    # polling loop. The guard that does lives in TimeMachine.get_router_values
    # (see _poller_running there) -- without it every gNMI poll was written to
    # InfluxDB twice.
    if not timemachine.time_machine_state['active']:
        print("Client connected, starting polling...")
        socketio.start_background_task(timemachine.get_router_values)
    else:
        print("Client connected, polling already started!")

@socketio.on('timestamp')
def handle_timestamp(data):
    timestamp = data.get('timestamp')
    print(f"Received timestamp for Time Machine: {timestamp}")
    timemachine.time_machine_state['timestamp'] = timestamp

@socketio.on('timemachine')
def handle_timemachine(data):
    is_active = data.get('time_machine_active')
    print(f"Received trigger for time machine: {is_active}")
    timemachine.time_machine_state['active'] = is_active
    if is_active:
        print([entry[0] for entry in timemachine.time_machine_deque])
    if not is_active:
        timemachine.time_machine_state["timestamp"] = None


if __name__ == '__main__':
    # use_reloader=False is load-bearing, not a style choice.
    #
    # debug=True switches on the Werkzeug reloader, which forks a child process
    # that re-imports this module. The module-level
    # threading.Thread(target=timemachine.get_router_values).start() above then
    # runs in BOTH processes, each with its own GnmiClient and its own Kafka
    # producer, so every gNMI poll is published twice. Measured: 3.93 points/s
    # per series where 0.5s polling gives 2.0 -> the 2.00x storage redundancy.
    # Verified by the child carrying WERKZEUG_RUN_MAIN=true with the parent as
    # its PPID.
    #
    # Note the factor is exactly 2 and does not grow with connected clients,
    # because time_machine_lock is held across the sleep in
    # TimeMachine.time_machine(): any number of poller loops WITHIN one process
    # is throttled to one poll per 0.5s. Only extra processes duplicate writes.
    socketio.run(app, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)

from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS

from modules.yamlinterpreter import YamlInterpreter
from modules.clabassistant import ClabAssistant
from modules.gnmiclient import GnmiClient
from modules.timemachine import TimeMachine

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*")

yamlinterpreter = YamlInterpreter(filepath="ma-fp-stumpf.clab.yml")
clabassistant = ClabAssistant()
gnmiclient = GnmiClient(yamlinterpreter=yamlinterpreter, clabassistant=clabassistant)
timemachine = TimeMachine(socketio=socketio, gnmiclient=gnmiclient)

topology = yamlinterpreter.topology_graph



@app.route("/topology", methods=["GET"])
def topology():
    return yamlinterpreter.topology_graph

@app.route("/clab-info", methods=["GET"])
def clab_info():
    return clabassistant.load_clab_info()

@socketio.on('connect')
def handle_connect():
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
    socketio.run(app, debug=True)

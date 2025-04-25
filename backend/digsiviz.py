from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import random
import time
from pygnmi.client import gNMIclient
import json
import yaml
import subprocess
import re
from collections import deque
import concurrent.futures
import threading
import sys

def load_yaml_from_file(file_path):
    with open(file_path, 'r') as file:
        return yaml.safe_load(file)

def convert_to_graph(topology):
    kinds = topology["topology"].get("kinds", {})

    nodes = []
    for node_id, node_props in topology["topology"]["nodes"].items():
        kind = node_props.get("kind")
        if kind and kind in kinds:
            node_props["image"] = kinds[kind].get("image")
        nodes.append({"id": node_id, **node_props})

    links = []
    for link in topology["topology"]["links"]:
        source, target = link["endpoints"]
        links.append({
            "source": source.split(":")[0],
            "target": target.split(":")[0],
            "source_interface": source.split(":")[1],
            "target_interface": target.split(":")[1],
        })

    return {"nodes": nodes, "links": links}


def load_clab_info():
    result = subprocess.run(["clab", "inspect", "--format", "json"], capture_output=True, text=True)
    if result.returncode != 0:
        print("Error while retrieving clab inspect.")
        return None

    data = json.loads(result.stdout)
    return data

def get_clab_ips():
    result = subprocess.run(["clab", "inspect", "--format", "json"], capture_output=True, text=True)
    if result.returncode != 0:
        print("Error while retrieving clab inspect.")
        return None

    data = json.loads(result.stdout)

    container_ips= {}

    for container in data.get("containers", []):
        full_name = container.get("name", "")
        ipv4_address = container.get("ipv4_address", "")

        name_split = full_name.split("-")
        hostname = name_split[-1]
        ip_clean = ipv4_address.split("/")[0] if ipv4_address else None

        if ip_clean:
            container_ips[hostname] = ip_clean

    return container_ips

def get_clab_router_ips():
    result = subprocess.run(["clab", "inspect", "--format", "json"], capture_output=True, text=True)
    if result.returncode != 0:
        print("Error while retrieving clab inspect.")
        return None

    data = json.loads(result.stdout)

    container_ips= {}

    for container in data.get("containers", []):
        group = container.get("group", "")
        full_name = container.get("name", "")
        ipv4_address = container.get("ipv4_address", "")

        name_split = full_name.split("-")
        hostname = name_split[-1]
        ip_clean = ipv4_address.split("/")[0] if (ipv4_address and group == "routers") else None

        if ip_clean:
            container_ips[hostname] = ip_clean

    return container_ips

def get_interfaces_by_name(topology, name: str):

    interfaces = []

    for link in topology["topology"]["links"]:
        for endpoint in link["endpoints"]:
            node, interface = endpoint.split(":")
            if node == name:
                interfaces.append(interface)

    return interfaces


def get_structured_data():
    ips = get_clab_router_ips()
    clab_topo = topology if isinstance(topology, dict) else json.loads(topology)

    gnmi_defaults = {"username": "admin", "password": "NokiaSrl1!", "port": 57401}
    routers_data = {}

    def fetch_router_data(hostname, ip):
        start_time = time.time()
        connected_interfaces = get_interfaces_by_name(clab_topo, hostname)
        gnmi_paths = [f"/interface[name={interface}]" for interface in connected_interfaces]

        target = (ip, gnmi_defaults["port"])
        credentials = (gnmi_defaults["username"], gnmi_defaults["password"])

        try:
            with gNMIclient(target=target, username=credentials[0], password=credentials[1], insecure=True) as gnmi:
                response = gnmi.get(path=gnmi_paths, encoding="json_ietf")

            router_interfaces = {}
            if "notification" in response:
                for notif in response["notification"]:
                    timestamp = notif.get("timestamp", None)
                    for update in notif.get("update", []):
                        path_str = update["path"]
                        match = re.search(r"interface\[name=(.*?)\]", path_str)
                        interface_name = match.group(1) if match else "unknown"
                        value = update["val"]

                        if interface_name not in router_interfaces:
                            router_interfaces[interface_name] = {}

                        router_interfaces[interface_name]["timestamp"] = timestamp
                        router_interfaces[interface_name].update(value)

            elapsed_time = time.time() - start_time
            print(f"(ROUTER {hostname}) Elapsed time: {elapsed_time} seconds")

            return hostname, router_interfaces
        except Exception as e:
            print(f"Error at {hostname} ({ip}): {e}")
            return hostname, None


    for hostname, ip in ips.items():
        hostname, data = fetch_router_data(hostname, ip)
        routers_data[hostname] = data

    return routers_data

time_machine_deque = deque(maxlen=120)
time_machine_lock = threading.Lock()
def time_machine():
    global time_machine_lock
    with time_machine_lock:
        start_time = time.time()
        data = get_structured_data()

        timestamp_utc = time.time()
        time_machine_deque.append((timestamp_utc, data))

        elapsed_time = time.time() - start_time
        sleep_time = max(0.5 - elapsed_time, 0)

        print(f"(TOTAL)Elapsed time: {elapsed_time} seconds")
        print(f"(TOTAL)Sleeping for: {sleep_time} seconds")

        time.sleep(sleep_time)

        return time_machine_deque[-1]


time_machine_state = {
    'timestamp': None,
    'active': False
}
def get_router_values():
    while True:
        try:
            if not time_machine_state['active'] and time_machine_state['timestamp'] is None:
                # Live Mode
                current_timestamp, response = time_machine()
                available_timestamps = [entry[0] for entry in time_machine_deque]

                socketio.emit('router_data', {'value': json.dumps(response)})
                socketio.emit('available_timestamps', {'values': available_timestamps})

            else:
                # Time Machine Mode
                target_timestamp = time_machine_state['timestamp'] or time_machine_deque[-1][0]
                print(f"Time Machine activated, Timestamp: {target_timestamp}")

                try:
                    index = next(i for i, entry in enumerate(time_machine_deque) if entry[0] == target_timestamp)
                    history_values = time_machine_deque[index][1]
                    available_timestamps = [entry[0] for entry in time_machine_deque]

                    socketio.emit('router_data', {'value': json.dumps(history_values)})
                    socketio.emit('available_timestamps', {'values': available_timestamps})

                except StopIteration:
                    print(f"No matching timestamp found for {target_timestamp}")

                time.sleep(0.5)



        except Exception as e:
            print(f"Error in get_router_values: {e}")
            socketio.emit('error', {'message': str(e)})
            time.sleep(1)  # Add delay before retrying



app = Flask(__name__)
CORS(app, resources={r"/*": {"origins":"*"}})
socketio = SocketIO(app, cors_allowed_origins="*")

topology = load_yaml_from_file("ma-fp-stumpf.clab.yml")
graph_data = convert_to_graph(topology)
print(graph_data)
clab_ips = get_clab_ips()




@app.route("/topology", methods=["GET"])
def get_topology():
    return jsonify(graph_data)

@app.route("/clab-info", methods=["GET"])
def get_clab_info():
    return load_clab_info()



gnmi_polling_on = False
@socketio.on('connect')
def handle_connect():
    global gnmi_polling_on

    if not gnmi_polling_on:
        print("Client connected, starting polling...")
        socketio.start_background_task(get_router_values)
    else:
        print("Client connected, polling already started!")

@socketio.on('timestamp')
def handle_timestamp(data):
    timestamp = data.get('timestamp')
    print(f"Received timestamp for Time Machine: {timestamp}")
    time_machine_state['timestamp'] = timestamp

@socketio.on('timemachine')
def handle_timemachine(data):
    is_active = data.get('time_machine_active')
    print(f"Received trigger for time machine: {is_active}")
    time_machine_state['active'] = is_active
    if is_active:
        print([entry[0] for entry in time_machine_deque])
    if not is_active:
        time_machine_state["timestamp"] = None


if __name__ == '__main__':
    socketio.run(app, debug=True)


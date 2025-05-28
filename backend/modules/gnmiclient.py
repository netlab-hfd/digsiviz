from pygnmi.client import gNMIclient
from modules.yamlinterpreter import YamlInterpreter
from modules.clabassistant import ClabAssistant
from modules.kafkaconnector import KafkaConnector
import re
import time
import concurrent.futures
import threading
from datetime import datetime, timezone
import json
from flatten_json import flatten

class GnmiClient():
    """
    Helper class to utilize pygnmi library to fetch gNMI data from routers of the topology using different methods and return it in a structured way.
    """
    
    username = "admin"
    password = "NokiaSrl1!"
    port = 57401

    router_ips = None


    subscription_data = None
    subscription_lock = None


    def __init__(self, yamlinterpreter: YamlInterpreter, clabassistant: ClabAssistant,  username = "admin", password = "NokiaSrl1!", port = 57401):
        super().__init__()
        self.username = username
        self.password = password
        self.port = 57401
        self.yaml = yamlinterpreter
        self.clab = clabassistant
        self.router_ips = self.clab.get_clab_router_ips()
        self.kafka = KafkaConnector("localhost:29092")
        if self.kafka.check_topic_exists("gnmi_data") is False:
            self.kafka.create_topic("gnmi_data", 1, 1)


    # def fetch_router_data(self, hostname, ip, timestamp_utc):
    #     """
    #     Fetches router data of a certain hostname and router IP using the gNMI GET command. Returns hostname and the gNMI data sorted by interfaces.
    #     """
    #     start_time = time.time()

    #     gnmi_defaults = {"username": self.username, "password": self.password, "port": self.port}
    #     connected_interfaces = self.yaml.get_interfaces_by_name(hostname)
        
    #     gnmi_paths = [f"/interface[name={interface}]" for interface in connected_interfaces]
    #     target = (ip, gnmi_defaults["port"])
    #     credentials = (gnmi_defaults["username"], gnmi_defaults["password"])

    #     try:
    #         with gNMIclient(target=target, username=credentials[0], password=credentials[1], insecure=True) as gnmi:
    #             response = gnmi.get(path=gnmi_paths, encoding="json_ietf")


    #         router_interfaces = {}
    #         if "notification" in response:
    #             for notif in response["notification"]:
    #                 timestamp = notif.get("timestamp", None)
    #                 for update in notif.get("update", []):
    #                     path_str = update["path"]
    #                     match = re.search(r"interface\[name=(.*?)\]", path_str)
    #                     interface_name = match.group(1) if match else "unknown"
    #                     value = update["val"]

    #                     if interface_name not in router_interfaces:
    #                         router_interfaces[interface_name] = {}

    #                     router_interfaces[interface_name]["timestamp"] = timestamp
    #                     router_interfaces[interface_name].update(value)


    #         elapsed_time = time.time() - start_time
    #         print(f"(Router {hostname}) Elapsed time for fetching gNMI data: {elapsed_time} seconds")

    #         json_data= {
    #             "timestamp": datetime.fromtimestamp(timestamp_utc, tz=timezone.utc).isoformat(),
    #             "hostname": hostname,
    #             "ip": ip,
    #             "interfaces": router_interfaces
    #         }

    #         json_flat = flatten(json_data, separator='.')

    #         json_string = json.dumps(json_flat, indent=None)
            

    #         self.kafka.send_message("gnmi_data", hostname, json_string)
            


            
    #         return hostname, router_interfaces

    #     except Exception as e:
    #         print(f"Error at {hostname} ({ip}): {e}")
    #         return hostname, None
        

    def fetch_router_data(self, hostname, ip, timestamp_utc):
        """
        Fetches router data of a certain hostname and router IP using the gNMI GET command. Returns hostname and the gNMI data sorted by interfaces.
        """
        start_time = time.time()

        gnmi_defaults = {"username": self.username, "password": self.password, "port": self.port}
        connected_interfaces = self.yaml.get_interfaces_by_name(hostname)
        
        gnmi_paths = [f"/interface[name={interface}]" for interface in connected_interfaces]
        target = (ip, gnmi_defaults["port"])
        credentials = (gnmi_defaults["username"], gnmi_defaults["password"])

        try:
            with gNMIclient(target=target, username=credentials[0], password=credentials[1], insecure=True) as gnmi:
                response = gnmi.get(path=gnmi_paths, encoding="json_ietf")


            if "notification" in response:
                for notif in response["notification"]:
                    timestamp = notif.get("timestamp", None)
                    for update in notif.get("update", []):
                        path_str = update["path"]
                        match = re.search(r"interface\[name=(.*?)\]", path_str)
                        interface_name = match.group(1) if match else "unknown"
                        value = update["val"]

                        value = self.convert_numbers(value)  # Convert string numbers to int/float


                        json_flat = flatten(value, separator='_')

                        converted_json_obj = self.convert_numbers(json_flat)

                        #converted_json= json.dumps(converted_json_obj, indent=None)

                        


                        json_data= {
                            "timestamp": datetime.fromtimestamp(timestamp_utc, tz=timezone.utc).isoformat(),
                            "hostname": hostname,
                            "ip": ip,
                            "interface_name": interface_name,
                            "interface_timestamp": timestamp,
                            "interface_data": converted_json_obj
                        }
                        

                        json_string = json.dumps(json_data, indent=None)
            
                        self.kafka.send_message("gnmi_data", hostname, json_string)


            elapsed_time = time.time() - start_time
            print(f"(Router {hostname}) Elapsed time for fetching gNMI data: {elapsed_time} seconds")

            return hostname, None # TODO: New Return

        except Exception as e:
            print(f"Error at {hostname} ({ip}): {e}")
            return hostname, None
        

        
    def get_structured_data_serial(self, timestamp_utc):
        """
        Runs the gNMI GET command for each router in the topology in serial.
        """
        routers_data = {}

        for hostname, ip in self.router_ips.items():
            hostname, data = self.fetch_router_data(hostname, ip, timestamp_utc)
            routers_data[hostname] = data
        
        return routers_data
    

    def get_structured_data_parallel(self, timestamp_utc):
        """
        Runs the gNMI GET command for each router in the topology in parallel.
        """
        routers_data = {}

        with concurrent.futures.ThreadPoolExecutor() as executor:
            results = executor.map(lambda args: self.fetch_router_data(args[0], args[1], timestamp_utc), self.router_ips.items())


        for hostname, data in results:
            routers_data[hostname] = data
        
        return routers_data
    


    def subscribe_gnmi_data(self):
        """
        Subscribes to the router data using gNMI SUBSCRIBE command. After a initial retrieval of all data, only changed values will be pushed and refreshed. Data is written to self.subscription_data! (ON_CHANGE mode)
        """
        if self.subscription_data is None:
            print("Initial fetch of all router data...")
            self.subscription_data = self.get_structured_data_parallel()

        self.subscription_lock = threading.Lock()

        gnmi_defaults = {"username": self.username, "password": self.password, "port": self.port}

        def set_nested(d, keys, value):
            for key in keys[:-1]:
                if key not in d:
                    d[key] = {}
                d = d[key]
            d[keys[-1]] = value

        def handle_updates(hostname, ip):
            while True:
                target = (ip, gnmi_defaults["port"])
                credentials = (gnmi_defaults["username"], gnmi_defaults["password"])

                connected_interfaces = self.yaml.get_interfaces_by_name(hostname)

                subscription = {
                    'subscription': [
                        {
                            'path': f'/interface[name={interface}]',
                            'mode': 'on_change'
                        } for interface in connected_interfaces
                    ],
                    'mode': 'stream',
                    'encoding': 'json'
                }

                try:
                    with gNMIclient(target=target, username=credentials[0], password=credentials[1], insecure=True) as gnmi:
                        print(f"(Router {hostname}) Starting gNMI subscription...")

                        for response in gnmi.subscribe2(subscribe=subscription):
                            if 'update' in response:
                                for update in response['update'].get('update', []):
                                    path_str = update['path']
                                    match = re.search(r"interface\[name=(.*?)\](.*)", path_str)

                                    if not match:
                                        print(f"Unexpected path format: {path_str}")
                                        continue

                                    interface_name = match.group(1)
                                    subpath = match.group(2).lstrip('/')

                                    value = update.get('val', None)
                                    if value is None:
                                        print(f"'val' missing for {interface_name} / {subpath}. Message: {value}")
                                        continue

                                    timestamp = response['update'].get('timestamp', time.time())

                                    with self.subscription_lock:
                                        if hostname not in self.subscription_data:
                                            self.subscription_data[hostname] = {}

                                        if interface_name not in self.subscription_data[hostname]:
                                            self.subscription_data[hostname][interface_name] = {}

                                        self.subscription_data[hostname][interface_name]["timestamp"] = timestamp

                                        if subpath:
                                            fields = subpath.split('/')
                                            set_nested(self.subscription_data[hostname][interface_name], fields, value)
                                        else:
                                            if isinstance(value, dict):
                                                self.subscription_data[hostname][interface_name].update(value)
                                            else:
                                                self.subscription_data[hostname][interface_name]["value"] = value

                except Exception as e:
                    print(f"Subscription error on {hostname} ({ip}): {e}")
                    print(f"Retrying subscription for {hostname} in 5 seconds...")
                    time.sleep(5)

        for hostname, ip in self.router_ips.items():
            thread = threading.Thread(target=handle_updates, args=(hostname, ip), daemon=True)
            thread.start()

 

    def convert_numbers(self,obj):
        if isinstance(obj, dict):
            return {k: self.convert_numbers(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.convert_numbers(elem) for elem in obj]
        elif isinstance(obj, str):
            # Versuch int, dann float
            try:
                return int(obj)
            except ValueError:
                try:
                    return float(obj)
                except ValueError:
                    return obj
        else:
            return obj
from pygnmi.client import gNMIclient
from modules.yamlinterpreter import YamlInterpreter
from modules.clabassistant import ClabAssistant
import re
import time
import concurrent.futures
import threading

class GnmiClient():
    
    
    username = "admin"
    password = "NokiaSrl1!"
    port = 57401


    def __init__(self, yamlinterpreter: YamlInterpreter, clabassistant: ClabAssistant,  username = "admin", password = "NokiaSrl1!", port = 57401):
        super().__init__()
        self.username = username
        self.password = password
        self.port = 57401
        self.yaml = yamlinterpreter
        self.clab = clabassistant


    def fetch_router_data(self, hostname, ip):
        start_time = time.time()

        gnmi_defaults = {"username": self.username, "password": self.password, "port": self.port}
        connected_interfaces = self.yaml.get_interfaces_by_name(hostname)
        
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
            print(f"(Router {hostname}) Elapsed time for fetching gNMI data: {elapsed_time} seconds")
            
            return hostname, router_interfaces

        except Exception as e:
            print(f"Error at {hostname} ({ip}): {e}")
            return hostname, None
        


        
    def get_structured_data_serial(self):
        ips = self.clab.get_clab_router_ips()
        routers_data = {}

        for hostname, ip in ips.items():
            hostname, data = self.fetch_router_data(hostname, ip)
            routers_data[hostname] = data
        
        return routers_data
    

    def get_structured_data_parallel(self):
        ips = self.clab.get_clab_router_ips()
        routers_data = {}

        with concurrent.futures.ThreadPoolExecutor() as executor:
            results = executor.map(lambda args: self.fetch_router_data(*args), ips.items())

        for hostname, data in results:
            routers_data[hostname] = data
        
        return routers_data

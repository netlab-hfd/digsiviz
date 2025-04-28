import json
import yaml
import subprocess

class ClabAssistant():
    def __init__(self):
        super().__init__()
        self.clab_info = self.load_clab_info()
        self.clab_router_ips = self.get_clab_router_ips()
        
    def load_clab_info(self):
        result = subprocess.run(["clab", "inspect", "--format", "json"], capture_output=True, text=True)
        if result.returncode != 0:
            print("Error while retrieving clab inspect.")
            return None

        data = json.loads(result.stdout)
        return data


    def get_clab_router_ips(self):
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
    



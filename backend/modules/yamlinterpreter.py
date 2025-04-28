import yaml

class YamlInterpreter():
    def __init__(self, filepath: str):
        super().__init__()
        self.filepath = filepath
        self.load_yaml_from_file()
        self.get_topology_graph_from_yaml()


    topology_yaml = None
    topology_graph = None

    def load_yaml_from_file(self):
        with open(self.filepath, 'r') as file:
            self.topology_yaml = yaml.safe_load(file)
            return self.topology_yaml
        
        
    def get_topology_graph_from_yaml(self):
        topology = self.load_yaml_from_file()
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


        self.topology_graph = {"nodes": nodes, "links": links}

        return self.topology_graph
    
    def get_interfaces_by_name(self, name: str):
        interfaces = []
        for link in self.topology_graph["links"]: 
            source = link["source"]
            target = link["target"]
            source_interface = link["source_interface"]
            target_interface = link["target_interface"]

            if source == name:
                interfaces.append(source_interface)
            elif target == name:
                interfaces.append(target_interface)
        return interfaces

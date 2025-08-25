# DigSiViz - Realtime Digital Twin Visualization
This repository contains the code and examples for the 
*DigSiViz*-Project, a Proof-of-Concept for visualizing Network Digital Twins (NDTs) 
in realtime by leveraging containerlab as network simulation 
layer and gNMI for realtime data retrieval.

## Table of Contents
- [Prerequirements](#Prerequirements)
- [Getting Started](#Getting-Started)
- [Samples](#Samples)
- [License](#License)
- [Contribute](#Contribute)

## Prerequirements
In order to run the project, you need to have 
the following dependencies installed on your system:

- [Docker](https://docs.docker.com/get-started/get-docker/)
- [Containerlab](https://containerlab.dev/install/)
- NodeJS
- Python v3.12.x

Refer to the documentation for the individual dependencies for installation 
or use your package manager.

## Getting Started
Clone the repository to your local computer:

```bash
git clone https://github.com/netlab-hfd/digsiviz
```

You need to install the dependencies of the frontend and backend individually.
Starting with the frontend, change into the 
`frontend` folder and run npm:

```bash
cd frontend
npm install
```

After that, the same must be done for the backend. Change into 
the `backend` folder and use the provided `requirements.txt` file to 
install all required packages. We recommend installing them into 
a virtual environment to avoid cluttering your python system packages:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Finally, you need to have a containerlab deployment 
running for the application to work. In the `backend` folder 
is a sample topology that can be deployed:

```bash
sudo clab deploy
```

The application is now ready for use.

## Samples

### iPerf3 with Triangular Topology

Follow the `Getting Started` guideline to achieve the running Containerlab topology and a ready-to-use application.

Start the backend by navigating to the `backend` folder and run:

```bash
python3 main.py
```

Start the frontend by navigating in to the `frontend` folder and run:

```bash
npm run dev
````

Open the frontend application by clicking on the link deployed by the previous `npm` command.
DigSiViz will open in your browser.

By clicking on `Topology`in the Navbar, you can open the topology visualization.
The frontend is now connected to the backend and displays the previously created containerlab topology.

![Start Screen](/samples/1-iperf3/Sample1-TopologyScreen.png "Starting the topology visualization.")

You can now start inspecting the delivered data by clicking on a node or link. You are also able to filter data.

![Displaying and Filtering Data](/samples/1-iperf3/Sample1-DisplayingAndFilteringData.png "Displaying and filtering monitoring data.")

To monitor an `iperf3` test, you have to run following commands:

```bash
clab inspect # (In backend folder where the clab.yml is located)
```

This command will show the container names that were instantiated by Containerlab.

Continue choosing two hosts, e.g. `clab-ma-fp-stumpf-h1` and `clab-ma-fp-stumpf-h2`.

Open a terminal and run:

```bash
docker exec -it clab-ma-fp-stumpf-h1 bash
```

In this window, you first retrieve the interface IP of the host using `ip a` command:
```bash
>ip a
[...]
1403: eth1@if1402: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default 
    link/ether aa:c1:ab:51:0d:cf brd ff:ff:ff:ff:ff:ff link-netnsid 1
    inet 10.0.1.101/24 scope global eth1
       valid_lft forever preferred_lft forever
    inet6 fe80::a8c1:abff:fe51:dcf/64 scope link 
       valid_lft forever preferred_lft forever
[...]
```

Run the `iperf3` server command on this host:

```bash
iperf3 -s
````

Open another terminal window and run

```bash
docker exec -it clab-ma-fp-stumpf-h2 bash
```

Start the iperf3 client using
```bash
iperf3 -c 10.0.1.101 -t 60s
```

The `iperf3`test is now in progress and you can monitor it in DigSiViz:

![Visualizing Live Traffic](/samples/1-iperf3/Sample1-LiveTraffic.png "Inspecting live traffic.")

You can also stop the live visualization and navigate through the saved timestamps using the Time Machine functionality:

![Using Time Machine](/samples/1-iperf3/Sample1-TimeMachine.png "Inspecting historical traffic using Time Machine.")

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
TODO: iperf3 with pictures?

TODO: More samples???

## License
TODO: Choose a License before publishing the paper

## Contribute
TODO: Contributions welcome or not?
<a id="top"></a>

# DigSiViz - Realtime Digital Twin Visualization

This repository contains the code and examples for the
*DigSiViz*-Project, a Proof-of-Concept for visualizing Network Digital Twins (NDTs)
in realtime by leveraging containerlab as network simulation
layer and gNMI for realtime data retrieval.

## Table of Contents

- [Visualization](#visualization)
  - [Prerequirements](#prerequirements)
  - [Getting Started](#getting-started)
  - [Samples](#samples)
  - [Publications](#publications)
- [Statistics Pipeline](#statistics-pipeline)
  - [Architecture and start order](#architecture-and-start-order)
  - [Dependencies](#dependencies)
  - [Start the services](#start-the-services)
  - [Deploy the topology](#deploy-the-topology)
  - [Run the pipeline](#run-the-pipeline)
  - [Verify InfluxDB](#verify-influxdb)
  - [Saturation test (iperf3)](#saturation-test-iperf3)
  - [Grafana](#grafana)
  - [Historical backfill (time-machine test)](#historical-backfill-time-machine-test)
  - [Teardown](#teardown)

---

# Visualization

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
cd digsiviz
```

You need to install the dependencies of the frontend and backend individually.
Starting with the frontend, change into the
`frontend` folder and run npm:

```bash
cd "$(git rev-parse --show-toplevel)/frontend"
npm install
```

After that, the same must be done for the backend. Change into
the `backend` folder and use the provided `requirements.txt` file to
install all required packages. We recommend installing them into
a virtual environment to avoid cluttering your python system packages:

```bash
cd "$(git rev-parse --show-toplevel)/backend"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Finally, you need to have a containerlab deployment
running for the application to work. In the `backend` folder
is a sample topology that can be deployed:

```bash
cd "$(git rev-parse --show-toplevel)/backend"
sudo clab deploy
```

The application is now ready for use.

## Samples

### iPerf3 with Triangular Topology

Follow the `Getting Started` guideline to achieve the running Containerlab topology and a ready-to-use application.

**On this branch, run the [Start the services](#start-the-services) step first
— `main.py` opens a Kafka producer at startup and will fail with a broker
connection error if the services are not up.**

Start the backend by navigating to the `backend` folder and run:

```bash
cd "$(git rev-parse --show-toplevel)/backend"
source .venv/bin/activate
python3 main.py
```

Start the frontend by navigating in to the `frontend` folder and run:

```bash
cd "$(git rev-parse --show-toplevel)/frontend"
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
cd "$(git rev-parse --show-toplevel)/backend"
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

## Publications

This project was presented at the **AnServApp Workshop** at **CNSM 2025**:

> **Paper:** “Using Network Digital Twin Visualization for Application Traffic Engineering”  
> **Authors:** Felix Stumpf, Leon-Niklas Lux, Sebastian Rieger  
> 📄 [Read the paper](https://opendl.ifip-tc6.org/db/conf/cnsm/cnsm2025/1571191564.pdf)  
> 🌐 [Conference website](https://www.cnsm-conf.org/)

[↑ Back to top](#top)

---

# Statistics Pipeline

The statistics pipeline pushes gNMI interface counters to Kafka, stores them in
InfluxDB via Telegraf, and exposes them in Grafana.

Each command block below is self-contained and can be run from **any** directory
inside the repository. Blocks that depend on a location start with
`cd "$(git rev-parse --show-toplevel)"`, which jumps to the repository root from
anywhere in the repo (no hardcoded paths). `docker exec` / `docker logs`
commands do not depend on the current directory.

## Architecture and start order

```
SRLinux routers (gNMI gRPC on :57400)
   │   GnmiClient performs a parallel gNMI GET every ~0.5s
   ▼
backend/main.py  →  TimeMachine thread  →  GnmiClient.fetch_router_data()
   │   one JSON per interface, produced to Kafka
   ▼
Kafka topics  gnmi_data  +  gnmi_stats        broker = localhost:29092
   │                                  │
   │ Telegraf consumes                │ kafkaconsumer.py consumes
   ▼                                  ▼
InfluxDB bucket "infldb"          prints messages (topic inspection)
   │
   ▼
Grafana  http://localhost:3000
```

InfluxDB is populated by Telegraf, not by `kafkaconsumer.py`. `main.py` opens a
Kafka producer at startup and reads router addresses from the running lab, so the
order is fixed:

```
docker compose up   →   clab deploy   →   python3 main.py
```

[↑ Back to top](#top)

## Dependencies

The pipeline packages (`confluent-kafka`, `flatdict`, `flatten-json`, `deepdiff`)
are already included in `backend/requirements.txt` and are installed by the
`Getting Started` step. Verify the backend imports resolve:

```bash
source "$(git rev-parse --show-toplevel)/backend/.venv/bin/activate"
python -c "import flask, flask_socketio, flask_cors, pygnmi, confluent_kafka, flatdict, flatten_json; print('deps ok')"
```

[↑ Back to top](#top)

## Start the services

This starts five containers: `zookeeper` and `kafka` (message bus), `influxdb`
(time series store), `telegraf` (Kafka→InfluxDB bridge), and `grafana`
(dashboards).

Run all compose commands from `docker/` so `.env` is picked up and `up`/`down`
share the same project name. The `cd` jumps there from anywhere in the repo.

```bash
cd "$(git rev-parse --show-toplevel)/docker"
docker compose up -d
```

[↳ Back to Samples](#samples)

Confirm the services report `Up`. Note `influx-setup` is a one-shot provisioner
(creates the downsample buckets/tasks) — it runs once and shows `Exited (0)`,
which is expected:

```bash
cd "$(git rev-parse --show-toplevel)/docker"
docker compose ps
```

If `telegraf` shows `Exited` with a `run out of available brokers` error, it
started before Kafka was ready. Restart it once Kafka is up:

```bash
cd "$(git rev-parse --show-toplevel)/docker"
docker compose restart telegraf
```

Web endpoints and credentials (from `docker/docker-compose.yml`):

| Service  | URL                   | Login / token                                                          |
|----------|-----------------------|-----------------------------------------------------------------------|
| InfluxDB | http://localhost:8086 | user `user` / `password`, org `myorg`, bucket `infldb`, token `mytoken` |
| Grafana  | http://localhost:3000 | `admin` / `admin`                                                     |

Kafka is reachable at `localhost:29092`. It is a TCP broker, not a web service,
so it cannot be opened in a browser.

[↑ Back to top](#top)

## Deploy the topology

This starts routers `r1`/`r2`/`r3` (SRLinux) and hosts `h1`/`h2`/`h3` (Linux).
The topology file lives in `backend/`.

> **Skip this if you already deployed the topology for the visualization
> ([Getting Started](#getting-started)) — it is the same lab.**

```bash
cd "$(git rev-parse --show-toplevel)"
sudo clab deploy -t backend/ma-fp-stumpf.clab.yml
```

Confirm all six nodes report `running` (SRLinux needs ~30–60s to become healthy):

```bash
cd "$(git rev-parse --show-toplevel)"
sudo clab inspect -t backend/ma-fp-stumpf.clab.yml
```

Topology: `h1`→`r1`, `h2`→`r2`, `h3`→`r3`; routers form a triangle
(`r1`-`r2`, `r1`-`r3`, `r2`-`r3`). Host IPs: `h1=10.0.1.101`, `h2=10.0.2.102`,
`h3=10.0.3.103`.

[↑ Back to top](#top)

## Run the pipeline

This starts the gNMI poll loop and the Kafka producer (with the Flask/SocketIO
backend). It runs in the foreground and does not return — run it in its **own
terminal** and leave it running; stop it later with `Ctrl+C`.

```bash
cd "$(git rev-parse --show-toplevel)/backend"
source .venv/bin/activate
python3 main.py
```

`main.py` emits only `ssl_target_name_override` warnings on success; confirm the
data flow through InfluxDB (next section).

To inspect the raw topic in a separate terminal (`kafkaconsumer.py` has no
`__main__`, so run the class directly; press `Ctrl+C` to stop it):

```bash
cd "$(git rev-parse --show-toplevel)/backend"
source .venv/bin/activate
python3 -c "from modules.kafkaconsumer import KafkaConsumerThread; KafkaConsumerThread('gnmi_data', None).run()"
```

Alternatively, read it directly from Kafka:

```bash
docker exec -it kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic gnmi_data --max-messages 3
```

[↑ Back to top](#top)

## Verify InfluxDB

Telegraf batches Kafka → InfluxDB every ~10s. The log lines change from
`Buffer fullness: 0` to `Wrote batch of N metrics`:

```bash
docker logs telegraf --tail 20
```

Confirm the measurements exist in the bucket (`network_interface` from
`gnmi_data`, `stats` from `gnmi_stats`):

```bash
docker exec influxdb influx query 'from(bucket:"infldb") |> range(start:-5m) |> group(columns:["_measurement"]) |> distinct(column:"_measurement")' --org myorg --token mytoken
```

[↑ Back to top](#top)

## Saturation test (iperf3)

This generates traffic across a router link. The hosts run
`wbitt/network-multitool`, which includes `iperf3`. The path `h1`→`h2` crosses
the `r1`-`r2` link.

Verify reachability first:

```bash
sudo docker exec clab-ma-fp-stumpf-h1 ping -c 3 10.0.2.102
```

Start the iperf3 server on `h2` (runs detached, produces no terminal output):

```bash
sudo docker exec -d clab-ma-fp-stumpf-h2 iperf3 -s
```

Run the client on `h1` for 60s:

```bash
sudo docker exec -it clab-ma-fp-stumpf-h1 iperf3 -c 10.0.2.102 -t 60
```

### Steady load with UDP

The TCP test above sawtooths (bursts then `0.00 Bytes` intervals) on a lossy
path: TCP interprets loss as congestion and backs off — by design. For a
**steady, controllable** offered load where every interval transfers, use UDP
with a target bitrate (`-u -b`). UDP does not back off, so it holds the rate:

```bash
sudo docker exec -it clab-ma-fp-stumpf-h1 iperf3 -u -c 10.0.2.102 -b 100M -t 20
```

The receiver line reports loss %, revealing the link's clean ceiling. This same
`-b <bitrate>` mechanism is how recorded traffic is **replayed** into the twin
(read a stored bitrate from InfluxDB, drive `iperf3 -u -b <that rate>`).

[↑ Back to top](#top)

## Grafana

Open <http://localhost:3000>, log in with `admin` / `admin`. The InfluxDB data
source and both dashboards are **provisioned automatically** at startup — no
manual UI clicking, nothing to import.

- **DigSiViz Traffic** — live per-second rates (top row, last 15m) plus the
  time machine over the 12 downsample tiers (bottom row, `Tier` dropdown).
- **DigSiViz Topology** — the topology weathermap: links coloured and labelled
  by bit rate, with a time slider to scrub through history and a
  `Granularity tier` dropdown to switch resolution.

> If a panel looks empty, check the time range **matches the tier** you selected
> — `traffic-52w` holds points a year apart, so `now-60d` shows nothing. And at
> genuine idle the weathermap correctly reads `0 b/s` between counter steps; use
> the **"Where is the traffic?"** strip under it to find the bursts.

**For how any of this works** — what is plugged into Grafana, the flow-panel
weathermap, the Flux naming contract, the srl-telemetry-lab provenance, the
version policy, and how to regenerate the topology — see
**[`grafana/README.md`](grafana/README.md)**.

[↑ Back to top](#top)


## Historical backfill (time-machine test)

The downsample **tasks only process recent data going forward**, and the raw
`infldb` bucket retains only ~1h. They will never build up years of history on
their own. To test that the tier buckets and the Grafana time machine actually
render multi-year data, seed the tiers with synthetic backdated points using
`influxdb/backfill.py`:

```bash
cd "$(git rev-parse --show-toplevel)/influxdb"
python3 backfill.py
```

What it does:
- Writes synthetic cumulative-counter points **directly into each tier bucket**
  (bypassing the cascade), backdated across that tier's own retention window at
  its own resolution. The multi-year span comes from the coarse buckets
  (`traffic-52w`, `-260w`, `-520w`), which have multi-year retention.
- Each point must fall **inside** the bucket's retention window — a point on the
  exact lower bound is rejected, so the oldest point is placed one step in.
- Uses the live schema (`network_interface` measurement, `statistics_out-octets`
  / `statistics_in-octets` base fields) so the Grafana panels render it
  unchanged. It is a mechanics test of the buckets + time machine, **not** the
  research pipeline. Re-running overwrites (idempotent).

Verify it worked:

```bash
# any tier has data spanning years:
docker exec influxdb influx query 'from(bucket:"traffic-52w") |> range(start:-15y) |> count()' --org myorg --token mytoken
```

Then open the **DigSiViz Traffic** dashboard (defaults to a `now-5y` window):
recent time shows the dense `raw`/`1m` series, older time shows the sparse
coarse tiers — the granularity design made visible.

### How the buckets get emptied (and how to refill them)

InfluxDB data lives in the named volumes `influxdb-data` / `influxdb-config`, so
`docker compose down` / `up` is **safe**. Two things still clear the tiers:

1. **`docker compose down -v`** — removes the volumes, and with them every
   bucket. This is also the only way to change
   `DOCKER_INFLUXDB_INIT_RETENTION` (the raw `infldb` retention), which applies
   at **init** only.
2. **`influx apply` recreating a bucket.** Re-applying an *unchanged* manifest is
   safe — `influx-setup` runs on every `docker compose up` and leaves row counts
   untouched. But any manifest edit that touches a bucket spec recreates that
   bucket and drops its data.

```bash
# refill after either of the above
cd "$(git rev-parse --show-toplevel)/influxdb"
python3 backfill.py
```

> Before named volumes existed, *all* InfluxDB data sat in the container's
> writable layer, so a plain `docker compose down` — no `-v` — destroyed every
> bucket. If you are on an older checkout, that is why your data keeps vanishing.

### Regenerating the downsample manifest

`influxdb/manifest.yml` (buckets + downsample tasks) is **generated**, not
hand-edited — hand-maintaining 12+ near-identical Flux blocks is error-prone.
Edit the tier table or aggregate list in `influxdb/generate_manifest.py` and
regenerate:

```bash
cd "$(git rev-parse --show-toplevel)/influxdb"
python3 generate_manifest.py       # rewrites manifest.yml
```

Each tier stores `mean`, `min`, `max` and `median` as separate field suffixes
(`statistics_out-octets_mean`, `_min`, `_max`, `_median`). `min`/`max` cascade
exactly across tiers, `mean` approximately, and `median`-of-medians is an
approximation.

[↑ Back to top](#top)

## Teardown

1) Stop `main.py` (and any running topic-inspection command) with `Ctrl+C` in
their terminals.

2) Stop the lab:

```bash
cd "$(git rev-parse --show-toplevel)"
sudo clab destroy -t backend/ma-fp-stumpf.clab.yml
```

3) Stop the services (add `-v` to also remove the Grafana volume):

```bash
cd "$(git rev-parse --show-toplevel)/docker"
docker compose down
```

InfluxDB has no persistent volume, so its stored metrics are discarded whenever
its container is recreated. Re-running the pipeline repopulates the bucket.

[↑ Back to top](#top)

# Reliable UDP File Transfer with SDN Dynamic Rerouting

A Python UDP file-transfer application with application-level reliability and an OS-Ken/OpenFlow 1.3 controller. The Mininet diamond topology has two paths between the sender and receiver. The controller installs IPv4/UDP forwarding rules, monitors flow counters, and recalculates routes when a link goes down or recovers.

## What is implemented

- UDP socket client and server; the receiver maintains independent sessions keyed by sender address and 128-bit session ID, so multiple transfers can be active without sharing reassembly state.
- 32-packet sliding window, sequence numbers, cumulative ACKs, per-packet timeout and selective retransmission of expired outstanding packets.
- CRC32 packet validation and final SHA-256/size verification before atomically committing the received file.
- Receiver-side out-of-order buffering, duplicate suppression, duplicate re-ACKs, idle-session cleanup, and counters/logging for duplicates and out-of-order datagrams.
- OpenFlow 1.3 shortest-path selection over the included diamond, port-status-driven rerouting and recovery, periodic flow-statistics polling, and safer IPv4-only flow replacement. The table-miss rule is preserved; unmatched traffic is dropped rather than flooded.
- Optional application-to-controller UDP telemetry on port 9999: the sender reports retransmission stalls and requests current path status. This requires a management IP for the controller reachable from the Mininet host; see below.
- Automated protocol and loopback end-to-end tests, plus a repeatable transport benchmark that exports CSV and a graph.

## Architecture and protocol

`client.py` reads the source file, splits it into 1000-byte DATA payloads, and sends within a bounded window. The server acknowledges the next expected sequence number. The receiver buffers out-of-order data and discards already-delivered duplicates. The sender retransmits only expired outstanding packets, not the entire window. Therefore, the accurate description is **selective retransmission with cumulative ACKs** (a Selective-Repeat-style receiver/sender hybrid), not Go-Back-N. FIN carries the expected byte count and SHA-256 digest; DONE is sent only after validation and file commit.

`topology.py` creates h1—s1—(s2/s3)—s4—h2. The controller computes a shortest available path between s1 and s4. The current demonstration has one sender/receiver host pair; the server supports multiple independent client sessions, but the included controller/topology host attachment is intentionally fixed to that pair.

## Environment setup

Use an Ubuntu VM/native Ubuntu host. Mininet and Open vSwitch require Linux network namespaces.

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3-venv python3-pip iproute2
sudo systemctl enable --now openvswitch-switch
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
sudo mn --test pingall
```

## Run

Terminal 1, controller:

```bash
source .venv/bin/activate
osken-manager controller.py --ofp-tcp-listen-port 6653
```

Terminal 2, Mininet:

```bash
sudo -E python3 topology.py
```

At the Mininet CLI, run the server in the background so the CLI remains usable:

```text
mininet> h2 python3 server.py &
mininet> h1 python3 client.py sample.txt 10.0.0.2
```

For a larger transfer, create a file on h1 and send it:

```text
mininet> h1 dd if=/dev/urandom of=/tmp/large.bin bs=1M count=20
mininet> h1 python3 client.py /tmp/large.bin 10.0.0.2
```

Files are saved in the receiver process's `received_files/` directory. Use absolute script paths if the Mininet host's working directory is not the project directory.

## Dynamic SDN and challenging scenarios

### Link failure and recovery

Start a large transfer, then:

```text
mininet> link s1 s2 down
```

The controller should log the port-down event, new path `s1-s3-s4`, and installed routes. The client timeout/retransmission mechanism recovers datagrams lost during convergence. Restore the link:

```text
mininet> link s1 s2 up
```

### Packet loss

```text
mininet> h1 tc qdisc add dev h1-eth0 root netem loss 5%
mininet> h1 python3 client.py /tmp/large.bin 10.0.0.2
mininet> h1 tc qdisc del dev h1-eth0 root
```

Inspect client retransmission totals and server duplicate/out-of-order counters. Always remove `netem` after the experiment.

### Flow monitoring and safe forwarding

Every five seconds the controller requests OpenFlow flow statistics and logs packet/byte totals. Route refresh deletes only IPv4 flow entries; the priority-zero table-miss entry remains. The packet-in handler intentionally drops unmatched traffic (except LLDP handling) to avoid flooding loops and duplicate application traffic in the diamond.

### Socket–SDN application telemetry

The controller listens for JSON telemetry on UDP port 9999. If a management interface/IP is configured and reachable from h1, start a transfer with:

```text
mininet> h1 python3 client.py /tmp/large.bin 10.0.0.2 --sdn-controller <CONTROLLER_MANAGEMENT_IP>
```

On retransmission timeout, the client sends a `transfer_stall` event and asks for `status`; the controller responds with active path and down ports. The telemetry listener binds to `0.0.0.0:9999` in the controller process. The management network must be configured by the operator; it is not the OpenFlow TCP connection and is not automatically routable from Mininet namespaces. Without it, file transfer continues normally and the client reports telemetry unavailable.

## Testing

```bash
./run_tests.sh
```

The suite compiles the Python modules, tests packet encoding/checksum rejection, and launches a real loopback UDP server/client to verify end-to-end file integrity and retransmission reporting.

## Performance evaluation

### Automated transport benchmark

```bash
python3 experiments/benchmark.py --size-mib 2 --trials 3
```

This compares a simple stop-and-wait UDP baseline with the reliable windowed UDP protocol on localhost. It writes `evidence/benchmark.csv` and, if matplotlib is installed, `evidence/benchmark.png`. These are transport-layer localhost measurements, not Mininet SDN failover results. Re-run on the project VM for your own machine's measurements.

### Mininet static-path vs failover comparison

Follow `experiments/mininet_failover.md` for a three-trial experiment that compares a forced single-path static baseline with active SDN failover, and records duration, throughput, retransmissions, recovery interval, and SHA-256 correctness. The actual failover table is intentionally left blank until measurements are taken in a running Mininet/OS-Ken environment; no simulated values are presented as experimental evidence.

Save terminal logs, controller logs, and `ovs-ofctl -O OpenFlow13 dump-flows s1` output under `evidence/`.

## Project structure

```text
client.py, server.py, protocol.py       UDP transfer and packet protocol
controller.py                           OS-Ken OpenFlow 1.3 controller
 topology.py                             Mininet diamond topology
 tests/                                  protocol + end-to-end integration tests
 experiments/benchmark.py                CSV/PNG transport benchmark
 experiments/mininet_failover.md         real SDN failover experiment procedure
 evidence/                               generated benchmark data and graph
```

## Limitations and viva preparation

- The topology's host pair and switch/port map are fixed for this demonstration. Multi-session transfer is supported at the server, but adding more host pairs requires extending controller host attachment/flow rules and topology.
- Telemetry requires a separately reachable management IP; OpenFlow control connectivity alone does not make UDP/9999 reachable from Mininet hosts.
- This is an educational reliable-UDP protocol, not TCP replacement or production congestion control. CRC32 detects accidental packet corruption; SHA-256 checks the completed file. The protocol does not provide encryption or peer authentication.
- Be ready to explain sequence numbers, cumulative ACK semantics, receiver buffering, duplicate suppression, selective retransmission, timeout trade-offs, flow matches/priorities, OpenFlow port-status events, flow-stat polling, shortest-path recomputation, and failover convergence.

# RoboParam Stress Testing

Three scripts that test different segments of the pipeline at different levels of realism.

```
stress_test.py     — inject directly into Redis → measures aggregator broadcast capacity
vla_stress_test.py — inject into SQS            → measures SQS + worker3 + Isaac Sim throughput
e2e_client.py      — full round-trip client      → measures end-to-end latency per simulated user
```

---

## System architecture (for reference)

```
VLA / e2e_client  →  SQS  →  worker3  →  Isaac Sim  →  Redis  →  Aggregator  →  WebSocket clients
                                                          ↑
                                               stress_test.py injects here
```

---

## Prerequisites

**Python 3.9+** and the following packages:

```bash
pip install -r requirements.txt
```

**AWS credentials** configured for `vla_stress_test.py` and `e2e_client.py`:

```bash
aws configure
# Enter your Access Key ID, Secret Access Key, and region (us-east-1)
```

Verify credentials are working:

```bash
aws sts get-caller-identity
```

**Services that must be running** depends on which script you use:

| Script | Redis | Aggregator | worker3 | Isaac Sim | AWS credentials |
|---|:---:|:---:|:---:|:---:|:---:|
| `stress_test.py` | ✓ | ✓ | | | |
| `vla_stress_test.py` | | | ✓ | ✓ | ✓ |
| `e2e_client.py` | | ✓ | ✓ | ✓ | ✓ |

---

## Script 1 — `stress_test.py`

Tests the aggregator in isolation. Bypasses SQS, worker3, and Isaac Sim entirely by injecting `SimResult` messages directly into Redis. Measures how many WebSocket clients the aggregator can broadcast to simultaneously.

**What it tests:**
- Aggregator broadcast throughput (msgs/sec delivered to N clients)
- Per-message end-to-end latency: Redis publish → WebSocket receive
- Connection capacity: how many clients can connect before errors appear

**When to use it:**
- You want to isolate the aggregator from the rest of the pipeline
- You want to test with a large number of WebSocket clients (50, 100, 200+)
- Isaac Sim or worker3 is not running

### Usage

```bash
cd stress-test

# Default run: test with 1, 5, 10, 50, 100 clients × 500,000 messages
python stress_test.py

# Custom client counts
python stress_test.py --clients 10 50 100 200

# Smaller message count for a quick test
python stress_test.py --clients 10 --messages 10000

# Rate-limited publish
python stress_test.py --clients 50 --rate 5000

# Save results to CSV
python stress_test.py --clients 1 10 50 100 --output results.csv

# Point at a different host
python stress_test.py \
    --redis-host 192.168.1.3 \
    --ws-url ws://192.168.1.5:8082/ws/results
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--clients` | `1 5 10 50 100` | Concurrent WebSocket client counts to test (space-separated) |
| `--messages` | `500000` | Messages to publish per run |
| `--ws-url` | `ws://localhost:8082/ws/results` | Aggregator WebSocket URL |
| `--redis-host` | `192.168.1.3` | Redis host |
| `--redis-port` | `6379` | Redis port |
| `--redis-channel` | `roboparam:results` | Redis pub/sub channel |
| `--rate` | unlimited | Max Redis publish rate in msg/s |
| `--connect-grace` | `3.0` | Seconds to wait for clients to connect before publishing |
| `--drain-grace` | `3.0` | Seconds to wait after publishing for in-flight messages |
| `--output` | — | Write results to a CSV file |

### Sample output

```
════════════════════════════════════════════════════════════════════════════════════
BENCHMARK SUMMARY
════════════════════════════════════════════════════════════════════════════════════
 Clients        Sent        Rcvd    Del%     Pub/s   p50ms   p95ms   p99ms    Errs
────────────────────────────────────────────────────────────────────────────────────
       1     500,000     500,000  100.0%    84,231     1.2     3.4     8.1       0
      10     500,000   5,000,000  100.0%    81,455     8.7    24.6    41.2       0
      50     500,000  25,000,000   98.3%    79,102    52.1   198.4   341.7       0
     100     500,000  42,300,000   84.6%    76,889   187.3   891.2  1423.5      14

════════════════════════════════════════════════════════════════════════════════════
BOTTLENECK ANALYSIS
════════════════════════════════════════════════════════════════════════════════════

  ──────────────────────────────────────  PROBLEMS  ───────────────────────────────

  1. [BROADCAST THREAD]  p99 latency grows super-linearly — WebSocketHandler.broadcast()
     is a single-threaded loop that blocks on each session.sendMessage() call.
     Degradation visible from 50 clients onward.
     Fix: run broadcast() in a thread pool, or replace CopyOnWriteArraySet
     iteration with per-session async writes.
```

---

## Script 2 — `vla_stress_test.py`

Replaces the VLA inference node. Publishes `JointAngleMessage` payloads directly to SQS using pre-generated sinusoidal trajectories. Tests how fast the full pipeline can process messages when the upstream producer is running at various concurrency levels.

**What it tests:**
- SQS publish throughput per thread
- SQS call latency (p50/p95/p99 of each `send_message()` call)
- Pipeline throughput (optionally, by monitoring the WebSocket)
- Whether worker3 + Isaac Sim can keep up with the publish rate

**When to use it:**
- You want to measure SQS and worker3 throughput without receiving results
- You want to see how quickly the pipeline falls behind under load

### Usage

```bash
cd stress-test

# Default run: test with 1, 5, 10, 20 threads × 500,000 messages
python vla_stress_test.py

# Custom thread counts
python vla_stress_test.py --threads 1 5 10 20

# Also monitor the WebSocket to see pipeline output rate
python vla_stress_test.py --threads 5 --messages 10000 \
    --ws-url ws://localhost:8082/ws/results

# Simulate realistic VLA inference cadence (~10 Hz)
python vla_stress_test.py --threads 1 --rate 10

# Assign specific device IDs to threads
python vla_stress_test.py --threads 4 \
    --device-ids arm-1 arm-2 arm-3 arm-4

# Save results
python vla_stress_test.py --threads 1 5 10 --output vla_results.csv
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--threads` | `1 5 10 20` | Concurrent publisher thread counts to test |
| `--messages` | `500000` | Messages per thread per run |
| `--queue-url` | *(project queue)* | SQS queue URL |
| `--region` | `us-east-1` | AWS region |
| `--device-ids` | `arm-1…arm-5` | Device IDs to cycle across threads |
| `--rate` | unlimited | Max publish rate per thread in msg/s |
| `--ws-url` | — | If provided, monitor WebSocket to measure pipeline output rate |
| `--output` | — | Write results to a CSV file |

### Sample output

```
════════════════════════════════════════════════════════════════════════════════════
BENCHMARK SUMMARY
════════════════════════════════════════════════════════════════════════════════════
 Threads        Sent    Errors    Total/s   p50ms   p99ms     WS Rcvd  Pipeline/s
────────────────────────────────────────────────────────────────────────────────────
       1     500,000         0         32    28.4    61.2         312         8.7
       5     500,000         0        148    30.1    74.8         891         9.1
      10     500,000         0        271    34.7   112.3        1204         9.3
      20     500,000         0        389    58.2   341.6        1587         9.8

════════════════════════════════════════════════════════════════════════════════════
BOTTLENECK ANALYSIS
════════════════════════════════════════════════════════════════════════════════════

  1. [PIPELINE CEILING]  Receive rate (9.8 msg/s) is less than half the send rate
     (389 msg/s) at 20 threads — SQS messages are queuing faster than worker3 can
     process them.
     worker3 bottleneck: @Scheduled(fixedDelay=500) polls up to 5 messages every
     500ms → max ~10 msg/s per instance.
```

---

## Script 3 — `e2e_client.py`

The most realistic test. Each simulated client has its own WebSocket connection to the aggregator and its own SQS sender thread. Measures the full round-trip latency from the moment a message is sent to SQS to when the SimResult arrives at the WebSocket.

**What it tests:**
- Full round-trip latency: SQS send → WebSocket receive (p50/p75/p95/p99)
- Isaac Sim latency in isolation (from `SimResult.latency` set by worker3)
- Latency breakdown: how much of the round-trip is Isaac Sim vs. the messaging stack
- Delivery rate per client
- Pipeline behaviour under multiple concurrent users

**When to use it:**
- You want to understand what a real user experiences end-to-end
- You want to compare Isaac Sim latency against messaging overhead
- You want to test with multiple simultaneous users each receiving their own results

### Thread model

Each client runs on its own OS thread. Inside that thread:

```
OS thread (client N)
├── asyncio loop  →  WebSocket connection (receives SimResults)
└── sub-thread    →  SQS sender (blocking boto3 calls)
```

This means `--threads 4` opens 4 WebSocket connections and 4 SQS sender sub-threads simultaneously.

### Usage

```bash
cd stress-test

# Smoke test — 1 client, 100 messages, rate-limited to 5 msg/s
python e2e_client.py --threads 1 --messages 100 --rate 5

# Default run: sweep 1, 2, 4, 8 clients × 500,000 messages
python e2e_client.py

# Custom thread counts
python e2e_client.py --threads 1 2 4 8

# Increase drain grace for large message counts
# (worker3 processes ~10 msg/s, so 1000 messages needs ~100s to drain)
python e2e_client.py --threads 2 --messages 1000 --drain-grace 120

# Save results
python e2e_client.py --threads 1 2 4 --output e2e_results.csv

# Custom endpoints
python e2e_client.py \
    --ws-url ws://127.0.0.1:8082/ws/results \
    --queue-url https://sqs.us-east-1.amazonaws.com/179895363911/roboparam-queue
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--threads` | `1 2 4 8` | Number of concurrent clients to test (each gets its own WebSocket connection and SQS sender) |
| `--messages` | `500000` | Messages per client per run |
| `--queue-url` | *(project queue)* | SQS queue URL |
| `--region` | `us-east-1` | AWS region |
| `--ws-url` | `ws://localhost:8082/ws/results` | Aggregator WebSocket URL |
| `--rate` | unlimited | Max send rate per client in msg/s |
| `--drain-grace` | `30.0` | Seconds to wait after sending for the pipeline to drain |
| `--output` | — | Write results to a CSV file |

### Latency matching

No correlation ID survives the pipeline — worker3 strips all fields except `deviceId`, `jointAngles`, `endEffector`, `collision`, and `latency`. Each client matches incoming SimResults by its own `deviceId` (`stress-arm-0`, `stress-arm-1`, etc.) and pairs them with the oldest unmatched send timestamp.

Because the aggregator broadcasts to all clients, each client receives SimResults for every device ID. Messages belonging to other clients are counted as `unmatched_receives` — this is expected behaviour, not an error.

### Drain grace

After all SQS sends finish, the script waits `--drain-grace` seconds for the pipeline to process the remaining backlog before collecting results. worker3 processes at roughly 10 msg/s. As a rule of thumb:

```
drain-grace (seconds) ≥ total_messages_sent / 10
```

For example, 4 clients × 100 messages = 400 messages → at least 40 seconds of drain grace.

### Sample output

```
  Results:
    Clients:                            4

  Send  (Client → SQS):
    Messages sent:                  400
    SQS errors:                       0
    Wall duration:                12.43s
    Total send rate:                 32 msg/s
    Per-client send rate:         7–9 msg/s

  Receive  (Aggregator → Client):
    Messages received:             1,521
    Unmatched receives:            1,321  (SimResults for other deviceIds)
    Matched (own deviceId):          200
    Delivery rate:                 50.0%  (increase --drain-grace to recover the rest)

  Round-trip latency  (SQS send → WebSocket receive):
    Samples:              200
    Min:                  412 ms
    Mean:                 687 ms
    p50:                  651 ms
    p75:                  798 ms
    p95:                 1,243 ms
    p99:                 1,891 ms
    Max:                 2,341 ms

  Isaac Sim latency  (from SimResult.latency, set by worker3):
    Samples:            1,521
    Mean:                 312 ms
    p50:                  298 ms
    p99:                  741 ms

  Latency breakdown (approximate means):
    Total round-trip:          687 ms  (100%)
    Isaac Sim (worker3):       312 ms   (45%)
    SQS + Redis + WebSocket:   375 ms   (55%)
```

---

## Choosing the right script

**"Is the aggregator fast enough to serve many users?"**
→ `stress_test.py` — bypasses everything, puts maximum pressure on the broadcast loop

**"How fast can we push joint angle commands into the system?"**
→ `vla_stress_test.py` — measures SQS publish throughput and worker3's processing ceiling

**"What does a real user experience from command to result?"**
→ `e2e_client.py` — full round-trip with per-client WebSocket connections

---
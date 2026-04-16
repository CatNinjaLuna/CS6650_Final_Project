# RoboParam — Distributed Robot Parameter Pipeline with VLA Inference

CS6650 Final Project · Northeastern University

Team: Carolina Li · Wenxuan Nie · Zhongjie Ren · Zhongyi Shi

Advisor: Prof. Vishal Rajpal

---

## Overview

RoboParam is a distributed system for real-time robotic arm control and VLA (Vision-Language-Action) inference. Action commands are queued via AWS SQS, consumed by a Spring Boot worker that forwards them to an NVIDIA Isaac Sim instance running a Franka Panda arm, and simulation results are streamed to a React + Three.js frontend via WebSocket.

The core distributed systems design decision is **SQS as a decoupling layer** — multiple concurrent users can enqueue commands simultaneously without blocking each other or the simulation worker. The number of active WebSocket sessions corresponds directly to the number of concurrent users the system supports.

---

## Architecture

```
Client (React + Three.js)
    |                       ↑
    | HTTP POST (action)    | WebSocket (receive-only)
    ↓                       |
AWS SQS              WebSocket Aggregator (port 8082)
(roboparam-queue)           ↑
    |                Redis pub/sub
    |               (roboparam:results)
    ↓                       ↑
worker3 (port 8083) ────────┘
    |
    | REST POST
    ↓
Isaac Sim @ 192.168.1.3:8011
(see /isaac-sim for setup)
```

**Critical design points:**

- The **client WebSocket is receive-only** — results are pushed from the aggregator to clients. Clients never publish through WebSocket.
- All **commands flow outbound via SQS only** — the client sends an HTTP POST which enqueues to SQS, never directly to worker3 or Isaac Sim.
- **worker3 is the only SQS consumer** — it polls, forwards to Isaac Sim via REST, then publishes the result to Redis.
- **Redis is used as pub/sub only** — not as a key-value store or database. There is no read operation to query. Messages are pushed to subscribers on arrival and do not persist.
- The **aggregator subscribes to Redis** and fans results out to all connected WebSocket sessions simultaneously — O(1) work per update regardless of client count.
- **Registration service** runs on port `8084` and manages lab/device metadata in memory — it is separate from the simulation pipeline and not related to Redis.

---

## Message Flow

```
Client → SQS → worker3 → Isaac Sim → worker3 → Redis → Aggregator → Client
```

Step by step:
1. Client sends an HTTP POST with `{"action": "push_red"}` which is enqueued to SQS
2. worker3 polls SQS (long-poll, 20s wait), deserializes the message
3. worker3 calls Isaac Sim REST endpoint — arm executes the action
4. Isaac Sim returns joint angles, end effector position, and collision status
5. worker3 publishes the result to Redis channel `roboparam:results`
6. Aggregator receives the Redis message and broadcasts to all connected WebSocket clients
7. All clients receive the update simultaneously via their receive-only WebSocket connection

---

## Services

| Service | Port | Description | Status |
|---|---|---|---|
| `worker3` | `8083` | Spring Boot SQS worker — polls action commands, calls Isaac Sim REST, publishes results to Redis | ✅ Running |
| `aggregator` | `8082` | Spring Boot WebSocket aggregator — subscribes to Redis pub/sub, fans out to all frontend clients | ✅ Running |
| `frontend` | `3000` | React + Three.js 3D URDF visualization of Franka Panda arm | ✅ Running |
| `registration-service` | `8084` | Manages lab and device metadata in memory — validates device existence for worker3 | ✅ Running |
| `vla` | — | OpenVLA inference server — produces 7-DOF joint deltas from camera observations | stretch goal — see [`/vla`](./vla) |
| Isaac Sim | `8011` | NVIDIA Isaac Sim running Franka Panda arm (Windows, NVIDIA GPU required) | ✅ Running — see [`/isaac-sim`](./isaac-sim) |

---

## Stack

- **Backend:** Java 17, Spring Boot 3.2, AWS SDK v2
- **Queue:** AWS SQS (long-poll, Standard queue)
- **Pub/Sub:** Redis 7 (Docker) — pub/sub only, not used as a database
- **Simulation:** NVIDIA Isaac Sim 5.x (Windows, RTX 5090) — see [`/isaac-sim`](./isaac-sim)
- **VLA Model:** OpenVLA (HuggingFace) — 7-DOF joint delta inference from camera feed
- **Frontend:** React, Three.js
- **Cloud:** AWS (SQS, us-east-1)

---

## Distributed Systems Design

### Why SQS over direct REST calls?
Direct REST from client → Isaac Sim would block — one slow client blocks all others. SQS decouples producers from the consumer entirely. Any number of clients can enqueue simultaneously without coordination, and worker3 drains the queue at its own pace. This is the core distributed coordination story and the key design decision of the system.

### Why Redis pub/sub over polling?
Polling the aggregator for new results would introduce latency and unnecessary load on Redis. Pub/sub pushes results to the aggregator the instant worker3 publishes — no polling delay, no wasted queries.

### Scalability
- **worker3 is stateless** — multiple instances can poll the same SQS queue concurrently; visibility timeout (30s) prevents duplicate processing
- **SQS as backpressure** — absorbs command bursts from concurrent users without overwhelming Isaac Sim; queue depth grows under load and drains as worker3 processes
- **Redis pub/sub decoupling** — worker3 and aggregator are fully independent; either can be restarted without affecting the other
- **Aggregator fan-out** — a single sim result is broadcast to N connected clients simultaneously; adding more clients does not increase per-update work

### Fault Tolerance
- **At-least-once delivery** — worker3 only deletes an SQS message after a successful Isaac Sim response; on failure, the message becomes visible again after the 30s visibility timeout and is retried automatically
- **Isaac Sim isolation** — worker3 handles Isaac Sim connection errors gracefully without crashing; failed messages are logged and retried via SQS visibility timeout
- **Client disconnect tolerance** — aggregator removes stale WebSocket sessions on disconnect; remaining clients are unaffected

### Consistency
- Commands are serialized through SQS — if multiple users send commands simultaneously, they are processed in arrival order by worker3
- Frontend receives **eventual consistency** — clients see the latest arm state within ~200ms; acceptable for visualization use case
- **Last write wins at Isaac Sim** — concurrent commands from multiple users are queued and applied sequentially; the arm reflects the most recently processed command

### Latency
- SQS long-poll (`waitTimeSeconds=20`) eliminates busy-waiting
- Measured end-to-end latency: **~33–69ms** (SQS receive → Isaac Sim response → Redis publish)
- VLA inference latency (~100–500ms for April 21 scope) runs asynchronously and does not block the real-time visualization pipeline

---

## Architecture FAQ

**Why not have the client send commands directly to worker3 via REST?**
That would couple the client to a single worker instance. If worker3 is slow or busy processing a command, the next client would block waiting for a response. SQS absorbs the burst — any number of clients can enqueue without waiting, and worker3 drains the queue independently.

**Why not use WebSocket for both sending commands and receiving results?**
WebSocket is bidirectional but stateful — maintaining send channels for every client adds complexity and a potential bottleneck at the aggregator. Separating concerns keeps the design clean: SQS handles durable, decoupled command delivery; WebSocket handles lightweight real-time fan-out to clients.

**What happens if worker3 goes down?**
Messages stay in SQS until the visibility timeout expires (30s), then become visible again for reprocessing. No messages are lost. When worker3 restarts, it resumes polling and drains the backlog.

**What happens if Isaac Sim goes down?**
worker3 catches the connection error, logs it, and does not delete the SQS message. The message retries after 30s. The rest of the system (aggregator, frontend, Redis) continues running unaffected.

**What happens if a client disconnects?**
The aggregator removes the stale WebSocket session on disconnect. All other connected clients continue receiving updates normally.

**How many concurrent users can the system handle?**
SQS and Redis pub/sub are effectively unbounded for this scale. The practical bottleneck is worker3 — a single poller processing one command at a time. Multiple worker3 instances can be added to increase throughput; SQS visibility timeout prevents duplicate processing. The April 21 stress test measures this curve directly.

**Why Standard SQS queue and not FIFO?**
Standard queue gives higher throughput and is sufficient for the current demo scope where actions are discrete and non-overlapping. FIFO guarantees strict ordering which matters when joint commands must be applied in exact sequence — that's a planned optimization for the April 21 showcase.

**Is Redis a database in this system?**
No. Redis is used exclusively as a pub/sub message broker on channel `roboparam:results`. There is no persistence, no reads, no key-value store usage. The registration service uses an in-memory store (Java `LinkedHashMap`) — also not Redis.

---

## Running the System

### Prerequisites

- Java 17+, Maven
- Docker (for Redis)
- AWS credentials configured (`aws configure`)
- Node.js 18+ (for frontend)
- Isaac Sim running on Windows machine — see [`/isaac-sim/README.md`](./isaac-sim)

### 1. Start Redis

```bash
docker run -d -p 6379:6379 redis:7
```

### 2. Configure AWS Credentials

#### Option A — AWS Academy (session-based)

Each time your AWS Academy lab session restarts, update credentials:

```bash
cat > ~/.aws/credentials << 'EOF'
[default]
aws_access_key_id=<your_key_id>
aws_secret_access_key=<your_secret>
aws_session_token=<your_session_token>
EOF
aws configure set region us-east-1
```

#### Option B — Personal AWS Account (permanent credentials)

No session token needed. One-time setup:

```bash
aws configure
# AWS Access Key ID: <your_access_key_id>
# AWS Secret Access Key: <your_secret_access_key>
# Default region name: us-east-1
# Default output format: json
```

This writes to `~/.aws/credentials` and `~/.aws/config` permanently — no need to update between sessions.

**IAM setup for personal account:**

1. Go to AWS Console → IAM → Users → Create user
2. Name the user (e.g. `snapgrid-worker`), disable console access
3. Attach the following policies directly:
    - `AmazonSQSFullAccess` — required for worker3 to poll and delete SQS messages
    - `AmazonEC2FullAccess` — required if deploying to EC2
    - `ServiceQuotasFullAccess` — optional, for quota monitoring
4. Go to Security credentials → Create access key → select "Local code"
5. Copy the Access Key ID and Secret Access Key into `aws configure`

**Minimum required SQS permissions** (if you prefer a least-privilege custom policy instead of `AmazonSQSFullAccess`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:SendMessage",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl"
      ],
      "Resource": "arn:aws:sqs:us-east-1:826889494728:roboparam-queue"
    }
  ]
}
```

![Personal AWS IAM user setup — snapgrid-worker with SQS and EC2 permissions](docs/screenshots/personal_aws_IAM.png)

Verify either option:
```bash
aws sqs list-queues
```

### 3. Run worker3

Edit `worker3/src/main/resources/application.yml` if needed:

```yaml
worker:
  sqs-queue-url: https://sqs.us-east-1.amazonaws.com/826889494728/roboparam-queue
  isaac-sim-base-url: http://192.168.1.3:8011
  isaac-sim-mock: false   # set to true for local stress testing without Isaac Sim — do not commit
```

```bash
cd worker3
mvn spring-boot:run
```

worker3 starts on port `8083` and begins polling SQS immediately.

### 4. Run aggregator

```bash
cd aggregator
mvn spring-boot:run
```

Aggregator starts on port `8082`, subscribes to Redis channel `roboparam:results`, and accepts WebSocket connections at `ws://localhost:8082/ws`.

### 5. Run frontend

```bash
cd frontend
npm install
npm start
```

Frontend starts on port `3000`.

---

## Testing

### Send a test action command via SQS

```bash
aws sqs send-message \
  --queue-url https://sqs.us-east-1.amazonaws.com/826889494728/roboparam-queue \
  --message-body '{"action": "push_red"}'
```

Valid actions: `push_red`, `push_green`, `reset`

### Expected worker3 log

```
INFO  worker3.IsaacSimClient : → Isaac Sim action=push_red
INFO  worker3.IsaacSimClient : ← Isaac Sim status=200 OK
INFO  worker3.SqsPoller      : Published to Redis: deviceId=arm-1 latency=50ms
```

### Expected aggregator log

```
Redis received: {"deviceId":"arm-1","module":"kinematics","jointAngles":[...],"endEffector":{"x":0.1071,"y":0.0005,"z":0.9277},"collision":false,"latency":50}
```

---

## Payload Schema

Full result payload published to Redis channel `roboparam:results` and broadcast over WebSocket to all connected clients:

```json
{
  "deviceId":    "arm-1",
  "module":      "kinematics",
  "jointAngles": [0.1, -0.3, 0.0, -1.5, 0.0, 1.8, 0.7],
  "endEffector": { "x": 0.1071, "y": 0.0005, "z": 0.9277 },
  "collision":   false,
  "latency":     50
}
```

---

## SQS Queue

| Property | Value |
|---|---|
| Queue name | `roboparam-queue` |
| Type | Standard (at-least-once delivery) |
| URL | `https://sqs.us-east-1.amazonaws.com/826889494728/roboparam-queue` |
| Region | `us-east-1` |
| Visibility timeout | 30s |
| Receive wait time | 20s (long-poll) |

---

## Local Development Without Isaac Sim

For stress testing or local development when Isaac Sim is not available, worker3 supports a mock mode that returns a hardcoded response instead of calling Isaac Sim.

Add to your **local** `application.yml` only — **do not commit this**:

```yaml
worker:
  isaac-sim-mock: true
```

With this flag, the full pipeline `SQS → worker3 → Redis → aggregator → WebSocket` runs locally with no dependency on Isaac Sim or any GPU. This is used for concurrent load testing (K threads → K SQS sends → K WebSocket connections).

---

## End-to-End Test Results

Full pipeline verified: **SQS → worker3 → Isaac Sim → Redis → aggregator → WebSocket → frontend**

| Test | Result |
|---|---|
| SQS queue creation | ✅ `roboparam-queue` live in `us-east-1` |
| worker3 startup | ✅ Started on port 8083 |
| SQS message ingestion | ✅ Message received and deserialized correctly |
| Isaac Sim reachability | ✅ Mac → Windows @ 192.168.1.3:8011 |
| Isaac Sim joint application | ✅ All 7 joints applied with correct values |
| Isaac Sim end effector | ✅ `endEffector` x/y/z returned in response |
| worker3 → Redis publish | ✅ Result published to `roboparam:results` |
| Aggregator Redis subscribe | ✅ Full payload received by aggregator |
| Aggregator → WebSocket | ✅ Payload pushed to connected clients |
| Full pipeline | ✅ SQS → worker3 → Isaac Sim → Redis → aggregator → WebSocket |

### Isaac Sim — Action Execution (push_red / push_green / reset)

Direct REST calls to the Isaac Sim action endpoint returning HTTP 200 with all 7 joint values.

![Isaac Sim action endpoint test — 200 OK with joint values](<docs/screenshots/isaac sim actions testing ok.png>)

### Full Pipeline — SQS to Frontend

SQS messages sent from Mac terminal, worker3 consuming and forwarding to Isaac Sim (latency ~33–69ms), results published to Redis, aggregator broadcasting to the React dashboard via WebSocket. Browser DevTools shows live WebSocket payload.

![Full pipeline: SQS to WebSocket to frontend](<docs/screenshots/end-to-end sqs msg test.png>)

---

## Future Optimizations

| Optimization | Description |
|---|---|
| OpenVLA inference caching | Cache results for repeated commands to reduce ~500ms inference latency to near-zero |
| Redis Cluster | Replace single Redis node with a cluster to eliminate pub/sub single point of failure |
| SQS FIFO Queue | Guarantee strict joint command ordering for deterministic robot motion |
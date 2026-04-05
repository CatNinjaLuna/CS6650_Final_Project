# SnapGrid — System Design

CS6650 Final Project · Northeastern University

Team: Carolina Li · Wenxuan Nie · Zhongjie Ren · Zhongyi Shi

Advisor: Prof. Vishal Rajpal

---

## 1. Overview

SnapGrid is a distributed VLA (Vision-Language-Action) training pipeline for robotic LEGO assembly. A Franka Panda arm runs inside NVIDIA Isaac Sim, executing assembly tasks while joint state and camera observations are streamed through an AWS SQS-backed worker pipeline to a React + Three.js frontend for real-time visualization. The same pipeline doubles as a data collection backbone for sim-to-real VLA policy training.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                         │
│           React + Three.js  (3D URDF visualization)         │
└────────────────────────────┬────────────────────────────────┘
                             │ WebSocket
┌────────────────────────────▼────────────────────────────────┐
│                     AGGREGATOR LAYER                        │
│              WebSocket Aggregator (Spring Boot)             │
│         Lab Registry · Device Registry · Session Mgmt      │
└────────────────────────────┬────────────────────────────────┘
                             │ SQS publish
┌────────────────────────────▼────────────────────────────────┐
│                      WORKER LAYER                           │
│   worker3 (Spring Boot) — SQS poll → Isaac Sim REST call   │
│      Port 8083 · Stateless · Horizontally scalable         │
│                    ✅ Verified working                       │
└────────────────────────────┬────────────────────────────────┘
                             │ REST  POST /roboparam/roboparam/update
┌────────────────────────────▼────────────────────────────────┐
│                   SIMULATION LAYER                          │
│     NVIDIA Isaac Sim 5.x  @  192.168.1.3:8211              │
│     Franka Panda arm · LEGO assembly scene · VLA rollout   │
│     Windows · RTX 5090 · ✅ Running                         │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Status |
|---|---|---|
| **Isaac Sim service** | Runs Franka Panda in LEGO assembly scene; accepts joint angle commands via REST; returns simulation state | ✅ Running |
| **worker3** | Polls SQS for joint angle messages; forwards to Isaac Sim; publishes result back to aggregator | ✅ Running on port 8083 |
| **WebSocket Aggregator** | Maintains persistent WebSocket connections to frontend clients; routes simulation state updates; holds lab/device registry | 🔲 In progress |
| **Frontend** | Renders live 3D URDF visualization of the Panda arm via Three.js; sends user commands upstream | 🔲 In progress |

---

## 3. API Contracts

### 3.1 SQS Queue

| Property | Value |
|---|---|
| Queue name | `roboparam-queue` |
| Type | Standard (at-least-once) |
| URL | `https://sqs.us-east-1.amazonaws.com/826889494728/roboparam-queue` |
| Region | `us-east-1` |
| Visibility timeout | 30s |
| Receive wait time | 20s (long-poll) |

### 3.2 SQS Message — Joint Angle Update

Messages enqueued by the aggregator, consumed by worker3.

```json
{
  "robotId": "panda-01",
  "jointAngles": [0.1, -0.3, 0.0, -1.5, 0.0, 1.8, 0.7],
  "timestamp": 1712345678901
}
```

| Field | Type | Description |
|---|---|---|
| `robotId` | `string` | Unique robot instance identifier |
| `jointAngles` | `double[7]` | 7-DOF Franka Panda joint positions (radians) |
| `timestamp` | `long` | Unix ms timestamp of the command |

---

### 3.3 Isaac Sim REST Endpoint

**`POST /roboparam/roboparam/update`**
Base URL: `http://192.168.1.3:8211`
Swagger: `http://192.168.1.3:8211/docs`

Request body:
```json
{
  "robotId": "panda-01",
  "jointAngles": [0.1, -0.3, 0.0, -1.5, 0.0, 1.8, 0.7],
  "timestamp": 1712345678901
}
```

Response:
```json
{
  "status": "ok",
  "robotId": "panda-01",
  "simulationState": {
    "jointPositions": [0.1, -0.3, 0.0, -1.5, 0.0, 1.8, 0.7],
    "endEffectorPose": { "x": 0.4, "y": 0.0, "z": 0.6 },
    "collisionDetected": false,
    "frameIndex": 1024
  }
}
```

---

### 3.4 WebSocket Events

**Server → Client** (aggregator pushes to frontend)

```json
{
  "event": "sim_update",
  "robotId": "panda-01",
  "simulationState": { ... },
  "timestamp": 1712345678950
}
```

**Client → Server** (frontend sends joint command)

```json
{
  "event": "joint_command",
  "robotId": "panda-01",
  "jointAngles": [0.1, -0.3, 0.0, -1.5, 0.0, 1.8, 0.7]
}
```

---

## 4. VLA Pipeline — Sim-to-Real

SnapGrid's Isaac Sim environment is designed as a data collection backbone for Vision-Language-Action policy training on LEGO assembly tasks.

### Task Definition
The Franka Panda arm is tasked with assembling LEGO bricks in Isaac Sim. Each episode:
1. A language instruction is issued (e.g. *"place the 2x4 red brick on top of the blue base"*)
2. The VLA policy rolls out joint angle commands
3. Camera observations + joint states are logged per frame

### Data Flow

```
Language Instruction
        ↓
   VLA Policy (inference)
        ↓
  Joint Angle Commands  ──→  SQS Queue  ──→  worker3  ──→  Isaac Sim
                                                               ↓
                                                    Sim State + Camera Obs
                                                               ↓
                                                     Training Data Store
```

### Sim-to-Real Validation
- Policies trained in Isaac Sim are evaluated against real Franka Panda trajectories
- Joint angle distributions and end-effector paths are compared between sim and real rollouts
- Isaac Sim's physics fidelity (rigid body + contact dynamics) is leveraged to minimize the sim-to-real gap for contact-rich LEGO assembly

---

## 5. Distributed Systems Design

### 5.1 Scalability
- **worker3 is stateless** — multiple instances can poll the same SQS queue concurrently; AWS SQS guarantees each message is delivered to exactly one worker via visibility timeout
- **SQS as backpressure** — queue depth naturally absorbs burst traffic from VLA policy rollouts without overwhelming Isaac Sim
- **WebSocket aggregator** scales horizontally behind a load balancer; session affinity ensures a client's WebSocket sticks to one aggregator instance

### 5.2 Fault Tolerance
- **At-least-once delivery** — worker3 only deletes a message from SQS after a successful Isaac Sim response; on failure the message re-appears after the 30s visibility timeout and retries automatically (verified in testing)
- **Isaac Sim isolation** — the simulation layer is a single node (GPU constraint); worker3 treats it as an external dependency with connection error handling to prevent cascading failures
- **Dead letter queue** — available for future configuration to route repeatedly failing messages for inspection

### 5.3 Consistency
- Joint angle commands are ordered per robot — SQS Standard queue with `robotId` keying provides best-effort ordering per robot instance
- The frontend receives eventual consistency — WebSocket pushes reflect the latest simulation state; acceptable for visualization use case
- VLA training data is written with frame indices to allow offline reordering if needed

### 5.4 Latency
- SQS long-polling (`waitTimeSeconds=20`) eliminates busy-waiting and reduces round-trip overhead
- Critical path: **SQS poll → Isaac Sim REST call → WebSocket push** — target end-to-end latency < 200ms per update
- VLA inference (GPU-bound) runs on the Isaac Sim host and is excluded from the distributed latency budget

---

## 6. Verified Test Results

| Test | Result |
|---|---|
| SQS queue creation | ✅ `roboparam-queue` live in `us-east-1` |
| AWS credentials (AWS Academy) | ✅ Verified via `aws sqs list-queues` |
| worker3 startup | ✅ Started in 1.036s on port 8083 |
| SQS message ingestion | ✅ Message received and deserialized correctly |
| Isaac Sim forwarding | ⚠️ `No route to host` — Mac/Windows on different networks; Isaac Sim otherwise running |
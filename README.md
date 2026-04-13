# Robo — Distributed VLA Training Pipeline for Robotic LEGO Assembly

CS6650 Final Project · Northeastern University

Team: Carolina Li · Wenxuan Nie · Zhongjie Ren · Zhongyi Shi

Advisor: Prof. Vishal Rajpal

---

## Overview

Robo is a distributed system for real-time robot parameter visualization and VLA (Vision-Language-Action) training for robotic LEGO assembly tasks. Joint angle updates are ingested via AWS SQS, forwarded to an NVIDIA Isaac Sim instance running a Franka Panda arm, and streamed to a React + Three.js frontend via WebSocket.

## Architecture

```
Frontend (React + Three.js)
        ↑ WebSocket
WebSocket Aggregator
        ↑ Redis pub/sub
   AWS SQS Queue
        ↑
    worker3 (this service)
        ↓ REST
  Isaac Sim @ 192.168.1.3:8011
```

## Services

| Service | Description | Status |
|---|---|---|
| `worker3` | Spring Boot SQS worker — polls joint angle messages, calls Isaac Sim REST endpoint, publishes results to Redis | ✅ Running |
| Isaac Sim | NVIDIA Isaac Sim running Franka Panda arm (Windows, NVIDIA GPU required) | ✅ Running |
| WebSocket Aggregator | Subscribes to Redis, fans out simulation results to frontend over WebSocket | ✅ Running |
| Frontend | React + Three.js 3D URDF visualization | ✅ Running |

## Stack

- **Backend:** Java 17, Spring Boot 3.2, AWS SDK v2
- **Queue:** AWS SQS (long-poll, Standard queue)
- **Pub/Sub:** Redis 7 (Docker)
- **Simulation:** NVIDIA Isaac Sim 5.x (Windows, RTX 5090)
- **Frontend:** React, Three.js
- **Cloud:** AWS (SQS, us-east-1)

## Isaac Sim — sim_state.py

`isaac-sim/sim_state.py` is the Script Editor entrypoint for Isaac Sim. Run it each session after pressing Play. It registers the `/roboparam/roboparam/update` POST endpoint and returns:

- `applied_joints` — joint angle confirmation for all 7 Franka Panda joints
- `end_effector` — world-space position of `/Franka/panda_hand` (`x, y, z`)
- `collision` — boolean, derived from PhysX contact report

## Running worker3

### Prerequisites

- Java 17+
- Maven
- AWS credentials configured (`aws configure`)
- Isaac Sim running and reachable at `192.168.1.3:8011`

### AWS Credentials (AWS Academy)

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

Verify:
```bash
aws sqs list-queues
```

### Configure

Edit `worker3/src/main/resources/application.yml`:

```yaml
worker:
  sqs-queue-url: https://sqs.us-east-1.amazonaws.com/826889494728/roboparam-queue
  isaac-sim-base-url: http://192.168.1.3:8011
```

### Build & Run

```bash
cd worker3
mvn spring-boot:run
```

worker3 starts on port `8083` and begins polling SQS immediately.

### Test

Send a test message to SQS:

```bash
aws sqs send-message \
  --queue-url https://sqs.us-east-1.amazonaws.com/826889494728/roboparam-queue \
  --message-body '{
    "robotId": "panda-01",
    "jointAngles": [0.1, -0.3, 0.0, -1.5, 0.0, 1.8, 0.7],
    "timestamp": 1712345678901
  }'
```

Expected worker3 log:
```
INFO  worker3.IsaacSimClient : → Isaac Sim robot=panda-01 joints=[0.1, -0.3, 0.0, -1.5, 0.0, 1.8, 0.7]
INFO  worker3.IsaacSimClient : ← Isaac Sim status=200 OK
INFO  worker3.SqsPoller      : Published to Redis: deviceId=arm-1 latency=50ms
```

Expected aggregator log:
```
Redis received: {"deviceId":"arm-1","module":"kinematics","jointAngles":[...],"endEffector":{"x":0.1071,"y":0.0005,"z":0.9277},"collision":false,"latency":50}
```

## End-to-End Test Results

Full pipeline verified: **SQS → worker3 → Isaac Sim → Redis → aggregator → WebSocket**

### Isaac Sim — Action Execution (push_red / push_green / reset)
Direct REST calls to the Isaac Sim action endpoint (`push_red`, `push_green`, `reset`) returning HTTP 200 with all 7 joint values. Confirms the simulation responds correctly to discrete action commands before wiring up the full SQS pipeline.

![Isaac Sim action endpoint test — 200 OK with joint values](<docs/screenshots/isaac sim actions testing ok.png>)

---

### Full Pipeline — SQS → worker3 → Isaac Sim → Aggregator → WebSocket → Frontend
End-to-end pipeline running live: SQS messages sent from Mac terminal, worker3 consuming and forwarding to Isaac Sim (latency ~33–69ms visible in logs), results published to Redis, aggregator broadcasting to the React dashboard via WebSocket. Browser DevTools shows the live WebSocket payload including `jointAngles`, `endEffector`, `collision`, and `latency`.

![Full pipeline: SQS to WebSocket to frontend](<docs/screenshots/end-to-end sqs msg test.png>)

---

## SQS Queue

| Property | Value |
|---|---|
| Queue name | `roboparam-queue` |
| Type | Standard |
| URL | `https://sqs.us-east-1.amazonaws.com/826889494728/roboparam-queue` |
| Region | `us-east-1` |
| Visibility timeout | 30s |
| Receive wait time | 20s (long-poll) |

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/roboparam/roboparam/update` | Send joint angles to Isaac Sim, returns joints + end effector + collision |
| `GET` | `/docs` | Swagger UI (Isaac Sim service) |
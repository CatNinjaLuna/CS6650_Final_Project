# SnapGrid — Distributed VLA Training Pipeline for Robotic LEGO Assembly

CS6650 Final Project · Northeastern University

Team: Carolina (Yuhan) Li · Wenxuan Nie · Zhongjie Ren · Zhongyi Shi

Advisor: Prof. Vishal Rajpal

---

## Overview

SnapGrid is a distributed system for real-time robot parameter visualization and VLA (Vision-Language-Action) training for robotic LEGO assembly tasks. Joint angle updates are ingested via AWS SQS, forwarded to an NVIDIA Isaac Sim instance running a Franka Panda arm, and streamed to a React + Three.js frontend via WebSocket.

## Architecture

```
Frontend (React + Three.js)
        ↑ WebSocket
WebSocket Aggregator
        ↑
   AWS SQS Queue
        ↑
    worker3 (this service)
        ↓ REST
  Isaac Sim @ 192.168.1.3:8211
```

## Services

| Service | Description | Status |
|---|---|---|
| `worker3` | Spring Boot SQS worker — polls joint angle messages, calls Isaac Sim REST endpoint | ✅ Running |
| Isaac Sim | NVIDIA Isaac Sim running Franka Panda arm (Windows, NVIDIA GPU required) | ✅ Running |
| WebSocket Aggregator | Streams simulation results to the frontend | 🔲 In progress |
| Frontend | React + Three.js 3D URDF visualization | 🔲 In progress |

## Stack

- **Backend:** Java 17, Spring Boot 3.2, AWS SDK v2
- **Queue:** AWS SQS (long-poll, Standard queue)
- **Simulation:** NVIDIA Isaac Sim 5.x (Windows, RTX 5090)
- **Frontend:** React, Three.js
- **Cloud:** AWS (SQS, us-east-1)

## Running worker3

### Prerequisites

- Java 17+
- Maven
- AWS credentials configured (`aws configure`)
- Isaac Sim running and reachable at `192.168.1.3:8211`

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
  isaac-sim-base-url: http://192.168.1.3:8211
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
```

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
| `POST` | `/roboparam/roboparam/update` | Send joint angles to Isaac Sim |
| `GET` | `/docs` | Swagger UI (Isaac Sim service) |
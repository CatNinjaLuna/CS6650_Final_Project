# Aggregator

Spring Boot service that subscribes to Redis pub/sub and fans out Isaac Sim results to frontend clients over WebSocket.

## Role in the Pipeline

```
SQS → worker3 → Isaac Sim → Redis (roboparam:results) → aggregator → WebSocket → frontend
```

- **worker3** processes SQS jobs, forwards joint angles to Isaac Sim, and publishes results to Redis
- **aggregator** subscribes to Redis and pushes each result to all connected frontend WebSocket clients in real time

## WebSocket Payload Schema

Frontend connects to `ws://localhost:8082/ws/results` and receives:

```json
{
  "deviceId":    "arm-1",
  "module":      "kinematics",
  "jointAngles": [0.1, -0.3, 0.2, -1.5, 0.0, 1.8, 0.4],
  "endEffector": { "x": 0.41, "y": 0.28, "z": 0.35 },
  "collision":   false,
  "latency":     14
}
```

| Field | Type | Description |
|---|---|---|
| `deviceId` | string | Robot identifier, sourced from `JointAngleMessage.robotId` |
| `module` | string | Task type, currently always `"kinematics"` |
| `jointAngles` | float[7] | Applied Franka Panda joint positions in radians |
| `endEffector` | object | World-space position of `/Franka/panda_hand` after joint application |
| `collision` | boolean | Whether Isaac Sim detected a collision during this step |
| `latency` | long | Round-trip time from SQS receive to Isaac Sim response, in ms |

## Prerequisites

| Dependency | Where | How |
|---|---|---|
| Redis 7 | Windows machine (192.168.1.3) | `docker run -d -p 6379:6379 --name redis redis:7` |
| worker3 | Windows machine | `mvn spring-boot:run` in `worker3/` |
| Isaac Sim | Windows machine | Launch with scene, run `sim_state.py` in Script Editor, press Play |

Port 6379 must be open in Windows Firewall for the Mac to reach Redis.

## How to Run

```bash
cd aggregator
mvn spring-boot:run
```

Aggregator starts on port **8082** and immediately connects to Redis at `192.168.1.3:6379`.

## Smoke Test

**1. Connect a WebSocket client:**
```bash
npx wscat -c ws://localhost:8082/ws/results
```

**2. Publish a test message to Redis:**
```bash
redis-cli -h 192.168.1.3 -p 6379 publish roboparam:results \
  '{"deviceId":"arm-1","module":"kinematics","jointAngles":[0.1,-0.3,0.2,-1.5,0.0,1.8,0.4],"endEffector":{"x":0.41,"y":0.28,"z":0.35},"collision":false,"latency":14}'
```

Expected: JSON appears in the `wscat` terminal and aggregator logs show:
```
Redis received: {"deviceId":"arm-1", ...}
```

## File Structure

```
aggregator/
├── pom.xml
├── README.md
└── src/main/
    ├── java/aggregator/
    │   ├── AggregatorApplication.java   # Spring Boot entry point
    │   ├── RedisConfig.java             # Registers RedisSubscriber on roboparam:results
    │   ├── RedisSubscriber.java         # Receives Redis messages, calls broadcast()
    │   ├── SimResult.java               # WebSocket payload POJO
    │   ├── WebSocketConfig.java         # Registers /ws/results endpoint
    │   └── WebSocketHandler.java        # Manages sessions, fans out messages
    └── resources/
        └── application.properties       # Port 8082, Redis host/port
```
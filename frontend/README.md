# RoboParam — Frontend

React + Vite frontend for the RoboParam distributed robot parameter visualization system.

## Stack

- **Framework**: React 18 (Vite)
- **Styling**: CSS variables (no external UI library)
- **3D rendering**: Three.js / React Three Fiber — Franka Panda GLB meshes
- **Transport**: WebSocket — connected to aggregator via ngrok

## Getting Started

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

> **Note:** The `.glb` files are tracked with Git LFS. On a new machine, run:
> ```bash
> brew install git-lfs
> git lfs install
> git lfs pull
> ```

## Project Structure

```
frontend/
├── public/
│   └── panda/              # Franka Panda GLB mesh files (Git LFS)
│       ├── link0.glb ~ link7.glb
│       ├── hand.glb
│       └── finger.glb
├── src/
│   ├── pages/
│   │   ├── LabRegistry.jsx   # Screen 1 — lab & device registry
│   │   ├── Dashboard.jsx     # Screen 2 — parameter dashboard
│   │   └── RobotViewer.jsx   # Three.js 3D arm component
│   ├── App.jsx               # Root component, handles page routing
│   ├── index.css             # Global styles and CSS variables
│   └── main.jsx              # Entry point
└── index.html
```

## Current State

| Feature | Status |
|---------|--------|
| Lab & device registry (FR-01/02) | ✅ Connected to registration service (port 8084) |
| Filter labs by module | ✅ Done |
| Parameter panel with 7-joint sliders (FR-03) | ✅ Done — slider + number input |
| Computed results panel | ✅ Live WebSocket data, mock fallback |
| Worker node latency panel | ✅ Mock data |
| Module coverage matrix (FR-08) | ✅ Mock data |
| WebSocket integration (FR-05) | ✅ Connected to aggregator via ngrok |
| 3D Franka Panda rendering (FR-06) | ✅ GLB meshes, joint angles wired to WebSocket |

## Backend Dependencies

### Registration Service (port 8084)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/labs/full` | Get all labs with their devices — used by Screen 1 |
| `GET` | `/labs` | Get all labs (no devices) |
| `POST` | `/labs` | Register a new lab |
| `POST` | `/labs/{labId}/devices` | Register a device under a lab |
| `GET` | `/labs/{labId}/devices` | Get all devices in a lab |
| `GET` | `/labs/{labId}/devices/{deviceId}` | Get a single device |

Start the service: `cd registration-service && mvn spring-boot:run`

### WebSocket Aggregator (port 8082)

Streams real-time simulation results to the frontend via Redis pub/sub.

Current public endpoint (ngrok):
```
wss://prodromal-elana-dedicatedly.ngrok-free.dev/ws/results
```

To run locally: `cd aggregator && mvn spring-boot:run`

## WebSocket Payload

Frontend connects to the aggregator WebSocket and receives:

```json
{
  "deviceId": "arm-1",
  "module": "kinematics",
  "jointAngles": [0.1, -0.3, 0.2, -1.5, 0.0, 1.8, 0.4],
  "endEffector": { "x": 0.41, "y": 0.28, "z": 0.35 },
  "collision": false,
  "latency": 14
}
```

- `jointAngles` — drives the 3D arm joint rotations in real time
- `endEffector` — displayed in the results panel
- `collision` — shown as a red warning when true
- `latency` — displayed in the results panel

## CSS Variables

All colors and theme values are defined in `index.css` under `:root`. To change the theme, update the variables there — no need to touch component files.

Key variables:
- `--bg-primary` — dark header / page background
- `--bg-card` — white card surfaces
- `--accent-blue` — module icons, latency values
- `--accent-green` — selected state, positive results
- `--accent-red` — collision warnings
# RoboParam — Frontend

React + Vite frontend for the RoboParam distributed robot parameter visualization system.

## Stack

- **Framework**: React 18 (Vite)
- **Styling**: CSS variables (no external UI library)
- **3D rendering**: Three.js / React Three Fiber _(coming soon)_
- **Transport**: WebSocket _(integration in progress)_

## Getting Started

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

## Project Structure

```
frontend/
├── src/
│   ├── pages/
│   │   ├── LabRegistry.jsx   # Screen 1 — lab & device registry
│   │   └── Dashboard.jsx     # Screen 2 — parameter dashboard
│   ├── App.jsx               # Root component, handles page routing
│   ├── index.css             # Global styles and CSS variables
│   └── main.jsx              # Entry point
└── index.html
```

## Current State

All UI is built and working with mock data:

| Feature | Status |
|---------|--------|
| Lab & device registry (FR-01/02) | ✅ Connected to registration service (port 8084) |
| Filter labs by module | ✅ Done |
| Parameter panel with joint sliders (FR-03) | ✅ Done |
| Computed results panel | ✅ Mock data |
| Worker node latency panel | ✅ Mock data |
| Module coverage matrix (FR-08) | ✅ Mock data |
| WebSocket integration (FR-05) | 🔲 Pending aggregator |
| 3D URDF rendering (FR-06) | 🔲 Pending WebSocket |

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

### WebSocket Aggregator (port TBD)

Streams real-time simulation results to the frontend. See WebSocket Integration section below.

## WebSocket Integration

Once the aggregator service is ready, replace the mock data in `ResultPanel` inside `Dashboard.jsx` with a live WebSocket connection.

Expected payload format from the aggregator:

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

## CSS Variables

All colors and theme values are defined in `index.css` under `:root`. To change the theme, update the variables there — no need to touch component files.

Key variables:
- `--bg-primary` — dark header / page background
- `--bg-card` — white card surfaces
- `--accent-blue` — module icons, latency values
- `--accent-green` — selected state, positive results
- `--accent-red` — collision warnings
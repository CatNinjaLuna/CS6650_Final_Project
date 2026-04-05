# Isaac Sim Setup — SnapGrid

## Requirements
- Windows 10/11 (macOS not supported)
- NVIDIA GPU with RTX cores (tested on RTX 5090)
- NVIDIA driver 580.88+
- 32GB RAM minimum

## Installation
1. Download Isaac Sim 5.x from https://developer.nvidia.com/isaac/sim
2. Extract to `C:\isaacsim`
3. Launch: double-click `isaac-sim.selector.bat` or run from terminal:
   ```
   cd C:\isaacsim
   isaac-sim.bat
   ```
4. First launch takes several minutes — wait for the full UI to load

## Loading the SnapGrid Scene
1. File → Open → `C:\isaacsim\roboparam_scene.usd`
2. The Franka Panda arm should appear in the viewport

## Starting the REST Endpoint
1. Open **Script Editor** (Window → Script Editor)
2. Open `roboparam_startup.py` from this folder
3. Hit **Run (Ctrl+Enter)**
4. You should see:
   ```
   RoboParam endpoint ready
   http://0.0.0.0:8011/roboparam/roboparam/update
   Swagger docs: http://0.0.0.0:8011/docs
   ```
5. Hit **Play** in the Isaac Sim toolbar to start the physics simulation

## Firewall Rules (first time only)
Run in PowerShell as Administrator:
```powershell
netsh advfirewall firewall add rule name="Allow ICMP" protocol=icmpv4:8,any dir=in action=allow
netsh advfirewall firewall add rule name="Isaac Sim 8011" protocol=TCP dir=in localport=8011 action=allow
```

## Verify It's Working
From another machine on the same network:
```bash
curl -X POST http://<your-windows-ip>:8011/roboparam/roboparam/update \
  -H "Content-Type: application/json" \
  -d '{"joint_angles": [0.1, -0.3, 0.0, -1.5, 0.0, 1.8, 0.7]}'
```

Expected response:
```json
{"status": "ok", "applied_joints": {"panda_joint1": 0.1, ...}, "joint_count": 7}
```

## Notes
- Isaac Sim binds to port **8011** (not 8211)
- Re-run `roboparam_startup.py` every time Isaac Sim restarts
- Find your Windows IP via `ipconfig` → look for IPv4 under WiFi adapter
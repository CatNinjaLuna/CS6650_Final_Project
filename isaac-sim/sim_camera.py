import threading
import base64
import time
from io import BytesIO

import numpy as np
from PIL import Image
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

import omni.isaac.core.utils.stage as stage_utils
from omni.isaac.sensor import Camera

# ── Config ────────────────────────────────────────────────────────────────────
CAMERA_PRIM_PATH = "/World/RobotCamera"
HOST = "0.0.0.0"
PORT = 8012
RESOLUTION = (640, 480)

# ── Init camera sensor ────────────────────────────────────────────────────────
camera = Camera(
    prim_path=CAMERA_PRIM_PATH,
    resolution=RESOLUTION,
)
camera.initialize()
camera.add_motion_vectors_to_frame()  # optional, keeps frame pipeline active

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI()

@app.get("/camera")
async def get_frame():
    try:
        camera.get_current_frame()  # tick the sensor
        rgba = camera.get_rgba()    # numpy array (H, W, 4) uint8

        if rgba is None:
            return JSONResponse({"error": "frame not ready"}, status_code=503)

        # RGBA → RGB → JPEG → base64
        img = Image.fromarray(rgba[:, :, :3], mode="RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return JSONResponse({
            "image": b64,
            "width": RESOLUTION[0],
            "height": RESOLUTION[1],
            "timestamp": time.time(),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# Start server ──────────────────────────────────────────────────────────────
import asyncio

def start():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info", loop="none")
    server = uvicorn.Server(config)
    loop.run_until_complete(server.serve())

threading.Thread(target=start, daemon=True).start()
print("[sim_camera] Camera server running on http://0.0.0.0:8012/camera")


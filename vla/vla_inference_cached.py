import base64
import boto3
import json
import time
import numpy as np
import requests
import redis
from io import BytesIO
from PIL import Image
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn
import torch
from transformers import AutoModelForVision2Seq, AutoProcessor

ISAAC_CAMERA_URL = "https://prodromal-elana-dedicatedly.ngrok-free.dev/camera"
SQS_QUEUE_URL    = "https://sqs.us-east-1.amazonaws.com/179895363911/roboparam-queue"
SQS_REGION       = "us-east-1"
MODEL_PATH       = "./openvla-7b"
HOST             = "0.0.0.0"
PORT             = 8090

# Delta scaling — applied on top of home position for visible arm motion
DELTA_SCALE = 3.0
HOME_JOINTS = [0.0, -17.0, 0.0, -86.0, 0.0, 69.0, 0.0]

JOINT_LIMITS = [
    (-2.8973,  2.8973),
    (-1.7628,  1.7628),
    (-2.8973,  2.8973),
    (-3.0718, -0.0698),
    (-2.8973,  2.8973),
    (-0.0175,  3.7525),
    (-2.8973,  2.8973),
]

print("[vla] Loading OpenVLA model...")
processor = AutoProcessor.from_pretrained(MODEL_PATH, trust_remote_code=True)
model = AutoModelForVision2Seq.from_pretrained(
    MODEL_PATH,
    torch_dtype=torch.float16,
    low_cpu_mem_usage=True,
    trust_remote_code=True,
).to("cuda").eval()
print("[vla] Model loaded.")

print("[cache] Connecting to Redis...")
cache = redis.Redis(host="localhost", port=6379, db=0)
cache.ping()
print("[cache] Redis connected.")

sqs = boto3.client("sqs", region_name=SQS_REGION)
app = FastAPI()


def cache_key(instruction: str) -> str:
    return f"vla:joints:{instruction.strip().lower()}"


def get_camera_frame():
    resp = requests.get(ISAAC_CAMERA_URL, timeout=5)
    resp.raise_for_status()
    b64 = resp.json()["image"]
    return Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")


def run_inference(image, instruction):
    inputs = processor(instruction, image).to("cuda", dtype=torch.float16)
    with torch.no_grad():
        action = model.predict_action(**inputs, unnorm_key="bridge_orig", do_sample=False)
    return action.tolist()


def scale_and_clamp(angles):
    scaled = [home + (a * DELTA_SCALE) for a, home in zip(angles, HOME_JOINTS)]
    return [float(np.clip(a, lo, hi)) for a, (lo, hi) in zip(scaled, JOINT_LIMITS)]


def publish_to_sqs(joint_angles):
    payload = {
        "deviceId": "vla-inference",
        "module": "openvla",
        "jointAngles": joint_angles,
        "endEffector": {"x": 0.0, "y": 0.0, "z": 0.0},
        "collision": False,
        "latency": 0.0,
    }
    sqs.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(payload))


@app.post("/infer")
async def infer(body: dict):
    instruction = body.get("instruction", "push the red block forward")
    t0 = time.time()

    try:
        key = cache_key(instruction)

        # Cache check
        cached = cache.get(key)
        if cached:
            joint_angles = json.loads(cached)
            publish_to_sqs(joint_angles)
            latency_ms = round((time.time() - t0) * 1000, 2)
            print(f"[cache] HIT  instruction='{instruction}' latency={latency_ms}ms")
            return JSONResponse({
                "status": "ok",
                "cache": "hit",
                "instruction": instruction,
                "joint_angles": joint_angles,
                "latency_ms": latency_ms,
            })

        # Cache miss — run inference
        image        = get_camera_frame()
        raw_angles   = run_inference(image, instruction)
        joint_angles = scale_and_clamp(raw_angles)

        # Write to cache
        cache.set(key, json.dumps(joint_angles))

        publish_to_sqs(joint_angles)
        latency_ms = round((time.time() - t0) * 1000, 2)
        print(f"[cache] MISS instruction='{instruction}' latency={latency_ms}ms")
        return JSONResponse({
            "status": "ok",
            "cache": "miss",
            "instruction": instruction,
            "raw_angles": raw_angles,
            "joint_angles": joint_angles,
            "delta_scale": DELTA_SCALE,
            "latency_ms": latency_ms,
        })

    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
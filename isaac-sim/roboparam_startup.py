# roboparam_startup.py
# Run this in Script Editor every time Isaac Sim launches
# It registers the RoboParam endpoint automatically

import carb
carb.settings.get_settings().set("/exts/omni.services.transport.server.http/host", "0.0.0.0")

from omni.services.core import main
from fastapi import APIRouter
import omni.usd
from pxr import UsdPhysics

router = APIRouter()

@router.post("/roboparam/update")
async def get_dynamic_update(params: dict):
    stage = omni.usd.get_context().get_stage()
    joint_paths = [
        "/Franka/panda_link0/panda_joint1",
        "/Franka/panda_link1/panda_joint2",
        "/Franka/panda_link2/panda_joint3",
        "/Franka/panda_link3/panda_joint4",
        "/Franka/panda_link4/panda_joint5",
        "/Franka/panda_link5/panda_joint6",
        "/Franka/panda_link6/panda_joint7",
    ]
    angles = params.get("joint_angles", [0.0] * 7)
    results = {}
    for path, angle in zip(joint_paths, angles):
        prim = stage.GetPrimAtPath(path)
        if prim:
            drive = UsdPhysics.DriveAPI.Get(prim, "angular")
            if drive:
                drive.GetTargetPositionAttr().Set(float(angle))
                results[path.split("/")[-1]] = angle
    return {
        "status": "ok",
        "applied_joints": results,
        "joint_count": len(results)
    }

main.register_router(router, prefix="/roboparam", tags=["RoboParam"])
print("RoboParam endpoint ready")
print("http://0.0.0.0:8211/roboparam/roboparam/update")
print("Swagger docs: http://0.0.0.0:8211/docs")


# sim_state.py
# Run this in Script Editor every time Isaac Sim launches
# It registers the RoboParam endpoint automatically

import carb
carb.settings.get_settings().set("/exts/omni.services.transport.server.http/host", "0.0.0.0")

from omni.services.core import main
from fastapi import APIRouter
import omni.usd
from pxr import UsdPhysics, Gf
import omni.physx as physx

router = APIRouter()

JOINT_PATHS = [
    "/Franka/panda_link0/panda_joint1",
    "/Franka/panda_link1/panda_joint2",
    "/Franka/panda_link2/panda_joint3",
    "/Franka/panda_link3/panda_joint4",
    "/Franka/panda_link4/panda_joint5",
    "/Franka/panda_link5/panda_joint6",
    "/Franka/panda_link6/panda_joint7",
]

END_EFFECTOR_PATH = "/Franka/panda_hand"

def get_end_effector_position(stage):
    prim = stage.GetPrimAtPath(END_EFFECTOR_PATH)
    if not prim:
        return None
    xform = omni.usd.get_world_transform_matrix(prim)
    translation = xform.ExtractTranslation()
    return {"x": round(translation[0], 4), "y": round(translation[1], 4), "z": round(translation[2], 4)}

def check_collision():
    physx_interface = physx.get_physx_interface()
    if physx_interface is None:
        return False
    # Get all active contact pairs involving the Franka root
    contacts = physx_interface.get_contact_report()
    if contacts is None:
        return False
    for contact in contacts:
        actor0 = str(contact.actor0)
        actor1 = str(contact.actor1)
        if "Franka" in actor0 or "Franka" in actor1:
            return True
    return False

@router.post("/roboparam/update")
async def get_dynamic_update(params: dict):
    stage = omni.usd.get_context().get_stage()
    angles = params.get("joint_angles", [0.0] * 7)

    results = {}
    for path, angle in zip(JOINT_PATHS, angles):
        prim = stage.GetPrimAtPath(path)
        if prim:
            drive = UsdPhysics.DriveAPI.Get(prim, "angular")
            if drive:
                drive.GetTargetPositionAttr().Set(float(angle))
                results[path.split("/")[-1]] = angle

    end_effector = get_end_effector_position(stage)
    collision = check_collision()

    return {
        "status": "ok",
        "applied_joints": results,
        "joint_count": len(results),
        "end_effector": end_effector,
        "collision": collision
    }

main.register_router(router, prefix="/roboparam", tags=["RoboParam"])
print("RoboParam endpoint ready")
print("http://0.0.0.0:8011/roboparam/roboparam/update")
print("Swagger docs: http://0.0.0.0:8011/docs")

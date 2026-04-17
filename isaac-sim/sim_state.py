import carb
carb.settings.get_settings().set("/exts/omni.services.transport.server.http/host", "0.0.0.0")

from omni.services.core import main
from fastapi import APIRouter
import omni.usd
from pxr import UsdPhysics, UsdGeom, Gf

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
RED_BOX_PATH = "/World/RedBox"
GREEN_BOX_PATH = "/World/GreenBox"

STIFFNESS = 1000.0
DAMPING = 200.0

# Block positions
RED_BOX_HOME   = Gf.Vec3d(0.3,  0.1, 0.05)
GREEN_BOX_HOME = Gf.Vec3d(0.3, -0.1, 0.05)
RED_BOX_PUSHED   = Gf.Vec3d(0.3,  0.4, 0.05)
GREEN_BOX_PUSHED = Gf.Vec3d(0.3, -0.4, 0.05)

# Joint poses
HOME_JOINTS      = [0.0,  -0.3, 0.0, -1.5,  0.0, 1.2, 0.0]
PUSH_RED_JOINTS  = [80.0,  75.0, 0.0, -90.0, 0.0, 60.0, 0.0]
PUSH_GREEN_JOINTS = [-80.0, 75.0, 0.0, -90.0, 0.0, 60.0, 0.0]


def get_end_effector_position(stage):
    prim = stage.GetPrimAtPath(END_EFFECTOR_PATH)
    if not prim:
        return None
    xform = omni.usd.get_world_transform_matrix(prim)
    translation = xform.ExtractTranslation()
    return {
        "x": round(translation[0], 4),
        "y": round(translation[1], 4),
        "z": round(translation[2], 4)
    }


def apply_joints(stage, angles):
    results = {}
    for path, angle in zip(JOINT_PATHS, angles):
        prim = stage.GetPrimAtPath(path)
        if prim:
            drive = UsdPhysics.DriveAPI.Get(prim, "angular")
            if drive:
                drive.GetStiffnessAttr().Set(STIFFNESS)
                drive.GetDampingAttr().Set(DAMPING)
                drive.GetTargetPositionAttr().Set(float(angle))
                results[path.split("/")[-1]] = angle
    return results


def move_block(stage, prim_path, position):
    prim = stage.GetPrimAtPath(prim_path)
    if prim:
        UsdGeom.XformCommonAPI(prim).SetTranslate(position)


async def run_trajectory(stage, steps, steps_per_pose=60):
    import omni.kit.app
    app = omni.kit.app.get_app()
    for angles in steps:
        apply_joints(stage, angles)
        for _ in range(steps_per_pose):
            await app.next_update_async()


def build_response(stage, results):
    return {
        "status": "ok",
        "applied_joints": results,
        "joint_count": len(results),
        "endEffector": get_end_effector_position(stage),
        "collision": False
    }


@router.post("/roboparam/update")
async def get_dynamic_update(params: dict):
    stage = omni.usd.get_context().get_stage()
    angles = params.get("joint_angles", [0.0] * 7)
    results = apply_joints(stage, angles)
    return build_response(stage, results)


@router.post("/roboparam/action")
async def perform_action(params: dict):
    stage = omni.usd.get_context().get_stage()
    action = params.get("action", "")

    if action == "push_red":
        await run_trajectory(stage, [HOME_JOINTS, PUSH_RED_JOINTS])
        results = apply_joints(stage, PUSH_RED_JOINTS)
        move_block(stage, RED_BOX_PATH, RED_BOX_PUSHED)

    elif action == "push_green":
        await run_trajectory(stage, [HOME_JOINTS, PUSH_GREEN_JOINTS])
        results = apply_joints(stage, PUSH_GREEN_JOINTS)
        move_block(stage, GREEN_BOX_PATH, GREEN_BOX_PUSHED)

    elif action == "reset":
        await run_trajectory(stage, [HOME_JOINTS])
        results = apply_joints(stage, HOME_JOINTS)
        move_block(stage, RED_BOX_PATH, RED_BOX_HOME)
        move_block(stage, GREEN_BOX_PATH, GREEN_BOX_HOME)

    else:
        return {"status": "error", "message": f"Unknown action: {action}"}

    return build_response(stage, results)


main.register_router(router, prefix="/roboparam", tags=["RoboParam"])
print("RoboParam endpoint ready")
print("http://0.0.0.0:8011/roboparam/roboparam/update")
print("http://0.0.0.0:8011/roboparam/roboparam/action")
print("Swagger docs: http://0.0.0.0:8011/docs")



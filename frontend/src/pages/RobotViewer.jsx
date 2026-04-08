// RobotViewer.jsx
// 3D viewport component — renders Franka Panda arm using React Three Fiber
// Currently loads individual GLB link meshes and composes them manually
// Joint angles are driven by WebSocket data from the aggregator

import { Canvas } from "@react-three/fiber"
import { OrbitControls, useGLTF } from "@react-three/drei"
import { useRef } from "react"

function PandaArm({ jointAngles = [0, 0, 0, 0, 0, 0, 0] }) {
    const link0 = useGLTF("/panda/link0.glb")
    const link1 = useGLTF("/panda/link1.glb")
    const link2 = useGLTF("/panda/link2.glb")
    const link3 = useGLTF("/panda/link3.glb")
    const link4 = useGLTF("/panda/link4.glb")
    const link5 = useGLTF("/panda/link5.glb")
    const link6 = useGLTF("/panda/link6.glb")
    const link7 = useGLTF("/panda/link7.glb")
    const hand  = useGLTF("/panda/hand.glb")

    return (
        <group>
            <primitive object={link0.scene.clone()} />
            <group position={[0, 0.333, 0]} rotation={[0, jointAngles[0], 0]}>
                <primitive object={link1.scene.clone()} />
                <group position={[0, 0, 0]} rotation={[jointAngles[1], 0, 0]}>
                    <primitive object={link2.scene.clone()} />
                    <group position={[0, 0.316, 0]} rotation={[0, jointAngles[2], 0]}>
                        <primitive object={link3.scene.clone()} />
                        <group position={[0.0825, 0, 0]} rotation={[0, jointAngles[3], 0]}>
                            <primitive object={link4.scene.clone()} />
                            <group position={[-0.0825, 0.384, 0]} rotation={[0, jointAngles[4], 0]}>
                                <primitive object={link5.scene.clone()} />
                                <group position={[0, 0, 0.088]} rotation={[0, jointAngles[5], 0]}>
                                    <primitive object={link6.scene.clone()} />
                                    <group position={[0.088, 0, 0]} rotation={[0, jointAngles[6], 0]}>
                                        <primitive object={link7.scene.clone()} />
                                        <primitive object={hand.scene.clone()} position={[0, 0, 0.107]} />
                                    </group>
                                </group>
                            </group>
                        </group>
                    </group>
                </group>
            </group>
        </group>
    )
}

export default function RobotViewer({ jointAngles }) {
    return (
        <Canvas camera={{ position: [1.5, 1.5, 1.5], fov: 50 }}>
            <ambientLight intensity={0.5} />
            <directionalLight position={[5, 5, 5]} intensity={1} />
            <PandaArm jointAngles={jointAngles} />
            <OrbitControls />
            <gridHelper args={[2, 10]} />
        </Canvas>
    )
}
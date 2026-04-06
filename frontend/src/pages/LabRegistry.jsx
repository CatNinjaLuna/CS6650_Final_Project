// LabRegistry.jsx
// Screen 1 — lab and device registry view.
//
// Responsibilities:
// - Displays all available labs and their connected device summaries
// - Lets the user filter labs by supported module
// - Lets the user select labs and start a simulation session
//
// Current implementation notes:
// - Uses local mock data for frontend-first development
// - Selection is currently lab-level for simplicity
// - In the integrated version, mockLabs should be replaced by GET /labs
//   from the registration service, and selection can be refined to device-level
//
// Props:
//   onStartSession(labs)
//   - Called when the user starts a session
//   - Receives the selected lab objects as the initial session configuration

import { useState } from "react"

const mockLabs = [
    {
        id: "lab-1",
        name: "Seattle FlexLab",
        location: "Seattle, WA",
        devices: { arm: 2, leg: 2, gripper: 1 },
        modules: ["kin", "col", "tra", "sen"],
        workers: 4,
        latency: 12,
    },
    {
        id: "lab-2",
        name: "Boston Robotics Hub",
        location: "Boston, MA",
        devices: { arm: 1 },
        modules: ["kin", "col", "tra", "sen"],
        workers: 2,
        latency: 38,
    },
    {
        id: "lab-3",
        name: "Austin Dynamics",
        location: "Austin, TX",
        devices: { biped: 1 },
        modules: ["kin", "col", "tra", "sen"],
        workers: 2,
        latency: 45,
    },
    {
        id: "lab-4",
        name: "Portland Node",
        location: "Portland, OR",
        devices: { arm: 1 },
        modules: ["kin", "col", "tra", "sen"],
        workers: 1,
        latency: 22,
    },
]

const ALL_TABS = ["all devices", "kinematics", "collision", "trajectory", "sensor"]

const MODULE_MAP = {
    kinematics: "kin",
    collision: "col",
    trajectory: "tra",
    sensor: "sen",
}

export default function LabRegistry({ onStartSession }) {
    const [selectedLabIds, setSelectedLabIds] = useState([])
    const [activeTab, setActiveTab] = useState("all devices")

    function toggleLab(id) {
        setSelectedLabIds(prev =>
            prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
        )
    }

    const filteredLabs = activeTab === "all devices"
        ? mockLabs
        : mockLabs.filter(lab => lab.modules.includes(MODULE_MAP[activeTab]))

    return (
        <div style={{ padding: "24px", background: "var(--bg-page)", minHeight: "100vh" }}>

            {/* Header — dark background to match Dashboard header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "var(--bg-primary)", margin: "-24px -24px 20px -24px", padding: "16px 24px" }}>
                <h1 style={{ fontSize: "18px", fontWeight: "500", color: "var(--text-primary)" }}>RoboParam — lab & device registry</h1>
                <span style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
          {selectedLabIds.length} lab{selectedLabIds.length !== 1 ? "s" : ""} selected
        </span>
            </div>

            {/* Filter tabs */}
            <div style={{ display: "flex", gap: "8px", marginBottom: "20px" }}>
                {ALL_TABS.map(tab => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        style={{
                            padding: "6px 14px",
                            borderRadius: "20px",
                            border: "1px solid var(--border)",
                            background: activeTab === tab ? "var(--accent-blue)" : "var(--bg-card)",
                            color: activeTab === tab ? "#fff" : "var(--text-secondary)",
                            fontSize: "12px",
                            cursor: "pointer",
                        }}
                    >
                        {tab}
                    </button>
                ))}
            </div>

            {/* Lab cards grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "16px" }}>
                {filteredLabs.map(lab => {
                    const isSelected = selectedLabIds.includes(lab.id)
                    return (
                        <div
                            key={lab.id}
                            onClick={() => toggleLab(lab.id)}
                            style={{
                                padding: "16px",
                                borderRadius: "8px",
                                border: isSelected ? "1px solid var(--accent-green)" : "1px solid var(--border)",
                                background: isSelected ? "var(--bg-card-selected)" : "var(--bg-card)",
                                cursor: "pointer",
                            }}
                        >
                            {/* Card header */}
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                                <div>
                                    <div style={{ fontWeight: "500", fontSize: "15px", color: "var(--text-on-card)" }}>{lab.name}</div>
                                    <div style={{ fontSize: "12px", color: "var(--text-on-card-secondary)", marginTop: "2px" }}>{lab.location}</div>
                                </div>
                                <div style={{
                                    width: "10px", height: "10px", borderRadius: "50%",
                                    background: isSelected ? "var(--accent-green)" : "var(--text-muted)",
                                    marginTop: "4px"
                                }} />
                            </div>

                            {/* Device badges */}
                            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "10px" }}>
                                {Object.entries(lab.devices).map(([type, count]) => (
                                    <span key={type} style={{
                                        padding: "2px 8px",
                                        borderRadius: "4px",
                                        background: "var(--bg-secondary)",
                                        border: "1px solid var(--border)",
                                        fontSize: "11px",
                                        color: "var(--text-primary)",
                                    }}>
                    {type} ×{count}
                  </span>
                                ))}
                            </div>

                            {/* Modules */}
                            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                                <span style={{ fontSize: "11px", color: "var(--text-on-card-secondary)" }}>modules:</span>
                                {lab.modules.map(m => (
                                    <span key={m} style={{
                                        width: "24px", height: "24px", borderRadius: "50%",
                                        background: "var(--accent-blue)",
                                        display: "flex", alignItems: "center", justifyContent: "center",
                                        fontSize: "9px", fontWeight: "bold", color: "#fff",
                                    }}>
                    {m}
                  </span>
                                ))}
                            </div>

                            {/* Workers + latency */}
                            <div style={{ fontSize: "12px", color: "var(--text-on-card)" }}>
                                {lab.workers} workers · {lab.latency}ms
                            </div>
                        </div>
                    )
                })}
            </div>

            {/* Coverage bar */}
            <div style={{
                padding: "12px 16px",
                background: "var(--bg-card)",
                border: "1px solid var(--border)",
                borderRadius: "8px",
                fontSize: "13px",
                color: "var(--text-on-card-secondary)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
            }}>
        <span>
          {selectedLabIds.length === 0
              ? "select devices above to configure session"
              : `${selectedLabIds.length} lab(s) selected`}
        </span>
                {selectedLabIds.length > 0 && (
                    <button
                        onClick={() => onStartSession(mockLabs.filter(l => selectedLabIds.includes(l.id)))}
                        style={{
                            padding: "8px 20px",
                            background: "var(--accent-green)",
                            color: "#000",
                            border: "none",
                            borderRadius: "6px",
                            cursor: "pointer",
                            fontWeight: "bold",
                            fontSize: "13px",
                        }}
                    >
                        Start Session →
                    </button>
                )}
            </div>

        </div>
    )
}
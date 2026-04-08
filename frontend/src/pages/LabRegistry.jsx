// LabRegistry.jsx
// Screen 1 — lab and device registry view.
//
// Responsibilities:
// - Displays all available labs and their connected device summaries
// - Lets the user filter labs by supported module
// - Lets the user select labs and start a simulation session
//
// Data source:
// - Fetches from GET http://localhost:8084/labs/full (registration service)
// - Falls back to mockLabs if the service is unavailable or returns empty
//
// Props:
//   onStartSession(labs)
//   - Called when the user starts a session
//   - Receives the selected lab objects as the initial session configuration

import { useState, useEffect } from "react"

// Fallback data used when registration service is unavailable
const mockLabs = [
    {
        labId: "lab-1",
        name: "Seattle FlexLab",
        location: "Seattle, WA",
        devices: [
            { deviceId: "arm-1", type: "arm", modules: ["kin", "col", "tra", "sen"], capacity: 2, inUse: 0 },
            { deviceId: "leg-1", type: "leg", modules: ["kin", "col", "tra", "sen"], capacity: 2, inUse: 0 },
            { deviceId: "gripper-1", type: "gripper", modules: ["kin", "col", "tra", "sen"], capacity: 1, inUse: 0 },
        ],
    },
    {
        labId: "lab-2",
        name: "Boston Robotics Hub",
        location: "Boston, MA",
        devices: [
            { deviceId: "arm-1", type: "arm", modules: ["kin", "col", "tra", "sen"], capacity: 1, inUse: 0 },
        ],
    },
    {
        labId: "lab-3",
        name: "Austin Dynamics",
        location: "Austin, TX",
        devices: [
            { deviceId: "biped-1", type: "biped", modules: ["kin", "col", "tra", "sen"], capacity: 1, inUse: 0 },
        ],
    },
    {
        labId: "lab-4",
        name: "Portland Node",
        location: "Portland, OR",
        devices: [
            { deviceId: "arm-1", type: "arm", modules: ["kin", "col", "tra", "sen"], capacity: 1, inUse: 0 },
        ],
    },
]

const ALL_TABS = ["all devices", "kinematics", "collision", "trajectory", "sensor"]

const MODULE_MAP = {
    kinematics: "kin",
    collision: "col",
    trajectory: "tra",
    sensor: "sen",
}

// Helper: get unique modules across all devices in a lab
function getLabModules(lab) {
    const moduleSet = new Set()
    lab.devices?.forEach(d => d.modules?.forEach(m => moduleSet.add(m)))
    return Array.from(moduleSet)
}

// Helper: count devices by type in a lab
function getDeviceCounts(lab) {
    const counts = {}
    lab.devices?.forEach(d => {
        counts[d.type] = (counts[d.type] || 0) + 1
    })
    return counts
}

export default function LabRegistry({ onStartSession }) {
    const [labs, setLabs] = useState([])
    const [selectedLabIds, setSelectedLabIds] = useState([])
    const [activeTab, setActiveTab] = useState("all devices")
    const [loading, setLoading] = useState(true)

    // Fetch labs from registration service on mount
    // Falls back to mock data if unavailable or empty
    useEffect(() => {
        fetch("http://localhost:8084/labs/full")
            .then(res => {
                if (!res.ok) throw new Error("Failed to fetch labs")
                return res.json()
            })
            .then(data => {
                if (!Array.isArray(data) || data.length === 0) setLabs(mockLabs)
                else setLabs(data)
            })
            .catch(err => {
                console.error("Failed to fetch labs:", err)
                setLabs(mockLabs)
            })
            .finally(() => setLoading(false))
    }, [])

    function toggleLab(id) {
        setSelectedLabIds(prev =>
            prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
        )
    }

    const filteredLabs = activeTab === "all devices"
        ? labs
        : labs.filter(lab => getLabModules(lab).includes(MODULE_MAP[activeTab]))

    if (loading) {
        return (
            <div style={{ padding: "24px", background: "var(--bg-page)", minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <span style={{ color: "var(--text-secondary)" }}>Loading labs...</span>
            </div>
        )
    }

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
                    const isSelected = selectedLabIds.includes(lab.labId)
                    const modules = getLabModules(lab)
                    const deviceCounts = getDeviceCounts(lab)

                    return (
                        <div
                            key={lab.labId}
                            onClick={() => toggleLab(lab.labId)}
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

                            {/* Device badges — derived from real device list */}
                            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "10px" }}>
                                {Object.entries(deviceCounts).map(([type, count]) => (
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

                            {/* Modules — derived from all devices in this lab */}
                            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
                                <span style={{ fontSize: "11px", color: "var(--text-on-card-secondary)" }}>modules:</span>
                                {modules.map(m => (
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

                            {/* Device count */}
                            <div style={{ fontSize: "12px", color: "var(--text-on-card)" }}>
                                {lab.devices?.length || 0} device{lab.devices?.length !== 1 ? "s" : ""} registered
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
              ? "select labs above to configure session"
              : `${selectedLabIds.length} lab(s) selected`}
        </span>
                {selectedLabIds.length > 0 && (
                    <button
                        onClick={() => onStartSession(labs.filter(l => selectedLabIds.includes(l.labId)))}
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
// Dashboard.jsx
// Screen 2 — parameter dashboard.
//
// Responsibilities:
// - Left panel: parameter sliders for each selected lab (mock version)
// - Center: 3D viewport placeholder (Three.js coming soon)
// - Right panel: computed results, worker node latency, module coverage matrix
//
// Current implementation notes:
// - ResultPanel and CoverageMatrix use mock data
// - Current parameter controls are lab-level for simplicity
// - TODO: replace with live WebSocket data from the aggregator service
//
// Props:
//   labs   — array of selected lab objects passed from App
//   onBack — callback to return to the Lab Registry

import { useState } from "react"

// Left panel: joint angle sliders per lab
function ParamPanel({ lab }) {
    const joints = ["joint 1", "joint 2", "joint 3"]
    const [values, setValues] = useState({ "joint 1": 0, "joint 2": 0, "joint 3": 0 })

    function handleChange(joint, val) {
        setValues(prev => ({ ...prev, [joint]: Number(val) }))
    }

    return (
        <div style={{ marginBottom: "16px" }}>
            <div style={{ fontSize: "12px", fontWeight: "bold", marginBottom: "8px", color: "var(--text-on-card-secondary)" }}>
                {lab.name}
            </div>
            {joints.map(joint => (
                <div key={joint} style={{ marginBottom: "10px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "var(--text-on-card-secondary)", marginBottom: "2px" }}>
                        <span>{joint}</span>
                        <span>{values[joint]}°</span>
                    </div>
                    <input
                        type="range"
                        min={-180}
                        max={180}
                        value={values[joint]}
                        onChange={e => handleChange(joint, e.target.value)}
                        style={{ width: "100%" }}
                    />
                </div>
            ))}
        </div>
    )
}

// Right panel: computed results + worker latency
// TODO: replace mock data with live WebSocket payload from aggregator
function ResultPanel() {
    const results = [
        { label: "arm-1 reach", value: "92%" },
        { label: "arm-1 collision", value: "high", warn: true },
        { label: "arm-1 EE x", value: "0.41m" },
        { label: "arm-1 EE y", value: "0.28m" },
        { label: "arm-1 cycle", value: "2.3s" },
    ]

    const workers = [
        { name: "kinematics", ms: 14 },
        { name: "collision", ms: 19 },
        { name: "trajectory", ms: 31 },
        { name: "aggregator", ms: 8 },
    ]

    return (
        <div>
            <div style={{ fontSize: "12px", color: "var(--text-on-card-secondary)", marginBottom: "8px" }}>computed results</div>
            {results.map(r => (
                <div key={r.label} style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", marginBottom: "6px" }}>
                    <span style={{ color: "var(--text-on-card-secondary)" }}>{r.label}</span>
                    <span style={{ color: r.warn ? "var(--accent-red)" : "var(--accent-green)", fontWeight: "bold" }}>{r.value}</span>
                </div>
            ))}

            <div style={{ fontSize: "12px", color: "var(--text-on-card-secondary)", margin: "16px 0 8px" }}>worker nodes</div>
            {workers.map(w => (
                <div key={w.name} style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", marginBottom: "6px" }}>
                    <span style={{ color: "var(--text-on-card-secondary)" }}>{w.name}</span>
                    <span style={{ color: "var(--accent-blue)" }}>{w.ms}ms</span>
                </div>
            ))}
        </div>
    )
}

// Right panel: lab x module coverage matrix with latency per cell
// TODO: replace mock latency values with live data from aggregator
function CoverageMatrix({ labs }) {
    const modules = ["kin", "col", "tra", "sen"]
    const rows = labs.map(lab => ({
        name: lab.name,
        coverage: {
            kin: "14ms",
            col: "19ms",
            tra: "31ms",
            sen: lab.modules.includes("sen") ? "12ms" : null,
        }
    }))

    return (
        <div style={{ marginTop: "20px" }}>
            <div style={{ fontSize: "12px", fontWeight: "500", color: "var(--text-on-card-secondary)", marginBottom: "10px", letterSpacing: "0.05em" }}>
                MODULE COVERAGE
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11px" }}>
                <thead>
                <tr>
                    <th style={{ textAlign: "left", color: "var(--text-on-card-secondary)", paddingBottom: "6px", fontWeight: "500" }}>lab</th>
                    {modules.map(m => (
                        <th key={m} style={{ textAlign: "center", color: "var(--text-on-card-secondary)", paddingBottom: "6px", fontWeight: "500" }}>{m}</th>
                    ))}
                </tr>
                </thead>
                <tbody>
                {rows.map((row, i) => (
                    <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
                        <td style={{ padding: "6px 0", color: "var(--text-on-card)", fontSize: "11px" }}>
                            {row.name}
                        </td>
                        {modules.map(m => (
                            <td key={m} style={{ textAlign: "center", padding: "6px 0" }}>
                                {row.coverage[m]
                                    ? <span style={{ color: "var(--accent-blue)" }}>{row.coverage[m]}</span>
                                    : <span style={{ color: "var(--text-muted)" }}>—</span>
                                }
                            </td>
                        ))}
                    </tr>
                ))}
                </tbody>
            </table>
        </div>
    )
}

export default function Dashboard({ labs, onBack }) {
    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg-primary)", color: "var(--text-primary)", fontFamily: "var(--font)" }}>

            {/* Header */}
            <div style={{ padding: "12px 24px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "16px" }}>
                <button onClick={onBack} style={{
                    background: "none",
                    border: "1px solid var(--border)",
                    color: "var(--text-primary)",
                    padding: "6px 14px",
                    borderRadius: "20px",
                    cursor: "pointer",
                    fontSize: "13px",
                }}>← Back</button>
                <span style={{ fontSize: "18px", color: "var(--text-primary)", fontWeight: "500" }}>
          RoboParam — parameter dashboard
        </span>
                <span style={{ fontSize: "13px", color: "var(--text-secondary)", marginLeft: "auto", fontWeight: "500" }}>
          {labs.map(l => l.name).join(" · ")} · {labs.reduce((sum, l) => sum + l.workers, 0)} workers
        </span>
            </div>

            {/* main body for three coloumn parts*/}
            <div style={{ display: "flex", flex: 1, overflow: "hidden", padding: "16px", gap: "16px" }}>

                {/* Left: paras panel */}
                <div style={{
                    width: "240px",
                    background: "var(--bg-card)",
                    border: "1px solid var(--border)",
                    borderRadius: "8px",
                    padding: "16px",
                    overflowY: "auto",
                    color: "var(--text-on-card)",
                }}>
                    <div style={{ fontSize: "12px", fontWeight: "500", color: "var(--text-on-card-secondary)", marginBottom: "16px", letterSpacing: "0.05em" }}>PARAMETERS</div>
                    {labs.map(lab => (
                        <ParamPanel key={lab.id} lab={lab} />
                    ))}
                </div>

                {/* middle：3D viewport */}
                <div style={{
                    flex: 1,
                    background: "var(--bg-secondary)",
                    border: "1px solid var(--border)",
                    borderRadius: "8px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                }}>
                    <div style={{ color: "var(--text-muted)", fontSize: "14px" }}>3D viewport — Three.js (coming soon)</div>
                </div>

                {/* right：result panel */}
                <div style={{
                    width: "220px",
                    background: "var(--bg-card)",
                    border: "1px solid var(--border)",
                    borderRadius: "8px",
                    padding: "16px",
                    overflowY: "auto",
                    color: "var(--text-on-card)",
                }}>
                    <div style={{ fontSize: "12px", fontWeight: "500", color: "var(--text-on-card-secondary)", marginBottom: "16px", letterSpacing: "0.05em" }}>RESULTS</div>
                    <ResultPanel />
                    <CoverageMatrix labs={labs} />
                </div>

            </div>
        </div>
    )
}
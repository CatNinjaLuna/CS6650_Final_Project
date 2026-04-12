import { useState } from "react"
import LabRegistry from "./pages/LabRegistry"
import Dashboard from "./pages/Dashboard"

// App.jsx
// Root component controlling high-level app flow:
// 1. LabRegistry → user selects labs/devices to form a session
// 2. Dashboard → displays active session (3D view + parameters)


// Note:
// - Routing is handled via local React state (no router library)
// - No backend integration here; data is passed down as props
// - selectedLabs represents the current session configuration
export default function App() {
    const [page, setPage] = useState("registry")
    const [selectedLabs, setSelectedLabs] = useState([])

    if (page === "dashboard") {
        return <Dashboard labs={selectedLabs} onBack={() => setPage("registry")} />
    }

    return (
        <LabRegistry
            onStartSession={(labs) => {
                setSelectedLabs(labs)
                setPage("dashboard")
            }}
        />
    )
}
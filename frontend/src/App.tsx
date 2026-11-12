import { lazy, Suspense } from 'react'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { Dashboard } from './pages/Dashboard'

// Recharts is ~370 kB; keep it out of the dashboard's initial bundle.
const MonitorDetail = lazy(() =>
  import('./pages/MonitorDetail').then((module) => ({ default: module.MonitorDetail })),
)

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <header className="topbar">
          <Link className="brand" to="/">
            <svg className="brand-mark" viewBox="0 0 26 26" aria-hidden="true">
              <path d="M3 14h5l3-8 5 15 3-7h4" />
            </svg>
            ApiTick
          </Link>
          <span className="topbar-note">local instance</span>
        </header>

        <main>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route
              path="/monitors/:id"
              element={
                <Suspense fallback={<div className="panel muted">Loading…</div>}>
                  <MonitorDetail />
                </Suspense>
              }
            />
          </Routes>
        </main>

        <footer className="footer">
          <div className="footer-inner">
            <span>ApiTick · local instance</span>
            <span>Checks run by the worker on this machine — history never leaves it.</span>
          </div>
        </footer>
      </div>
    </BrowserRouter>
  )
}

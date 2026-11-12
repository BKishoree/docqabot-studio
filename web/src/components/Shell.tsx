import { useQueryClient } from '@tanstack/react-query'
import { Activity, FileText, Menu, MessageSquareText, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { keys } from '../api/queries'
import { announce, LiveRegions } from '../lib/announce'
import { plural } from '../lib/format'
import { useSystem } from '../lib/system'
import { ConversationList } from './ConversationList'
import { Notices } from './Notices'
import { SystemIndicator, summarize } from './SystemIndicator'

export function Shell() {
  const sys = useSystem()
  const qc = useQueryClient()
  const location = useLocation()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const railRef = useRef<HTMLElement>(null)

  // Database came back: reload everything that failed while it was down (S9).
  const wasDown = useRef(false)
  useEffect(() => {
    if (sys.databaseDown) {
      if (!wasDown.current) announce('The database is unavailable.', 'assertive')
      wasDown.current = true
    } else if (wasDown.current && sys.health) {
      wasDown.current = false
      announce('The database is available again.')
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== keys.health[0] })
    }
  }, [sys.databaseDown, sys.health, qc])

  // Close the drawer on navigation (state adjusted during render, not in an effect).
  const [lastPath, setLastPath] = useState(location.pathname)
  if (lastPath !== location.pathname) {
    setLastPath(location.pathname)
    setDrawerOpen(false)
  }

  // Drawer: Escape closes, focus moves in and back out.
  useEffect(() => {
    if (!drawerOpen) return
    const first = railRef.current?.querySelector<HTMLElement>('a, button')
    first?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setDrawerOpen(false)
        menuButton.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  const closeDrawer = () => setDrawerOpen(false)
  const status = summarize(sys)

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <LiveRegions />

      <header className="topbar">
        <button
          ref={menuButton}
          type="button"
          className="icon-btn"
          aria-label="Open navigation"
          aria-expanded={drawerOpen}
          aria-controls="rail"
          onClick={() => setDrawerOpen(true)}
        >
          <Menu size={20} aria-hidden="true" />
        </button>
        <NavLink to="/" className="wordmark" end>
          <span>
            DocQA <span className="hl">Studio</span>
          </span>
        </NavLink>
        <NavLink to="/status" className="icon-btn topbar-status" aria-label={`System status: ${status.label}`}>
          <Activity size={18} aria-hidden="true" />
        </NavLink>
      </header>

      <div className="scrim" hidden={!drawerOpen} onClick={closeDrawer} aria-hidden="true" />

      <nav
        id="rail"
        ref={railRef}
        className={`rail${drawerOpen ? ' is-open' : ''}`}
        aria-label="Workspace"
      >
        <div className="rail-head">
          <NavLink to="/" className="wordmark" end onClick={closeDrawer}>
            <span>
              DocQA <span className="hl">Studio</span>
            </span>
            <small>Answers with their sources</small>
          </NavLink>
          <button
            type="button"
            className="icon-btn rail-close"
            aria-label="Close navigation"
            onClick={() => {
              closeDrawer()
              menuButton.current?.focus()
            }}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="nav">
          <NavLink to="/" end onClick={closeDrawer}>
            <MessageSquareText size={16} aria-hidden="true" /> Ask
          </NavLink>
          <NavLink to="/library" onClick={closeDrawer}>
            <FileText size={16} aria-hidden="true" /> Library
            {sys.documentsLoaded && (
              <span className="count" aria-label={`${plural(sys.readyCount, 'document')} ready`}>
                {sys.readyCount}
              </span>
            )}
          </NavLink>
          <NavLink to="/status" onClick={closeDrawer}>
            <Activity size={16} aria-hidden="true" /> Status
          </NavLink>
        </div>

        <ConversationList onNavigate={closeDrawer} />

        <div className="rail-foot">
          <SystemIndicator sys={sys} onNavigate={closeDrawer} />
        </div>
      </nav>

      <div className="main">
        <Notices sys={sys} />
        <main id="main" tabIndex={-1} style={{ outline: 'none' }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}

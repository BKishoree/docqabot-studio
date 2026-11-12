import { CircleAlert, CircleCheck, CircleDashed, CircleX } from 'lucide-react'
import { Link } from 'react-router'
import type { SystemState } from '../lib/system'

/** Compact system state in the rail; always links to /status. */
export function SystemIndicator({ sys, onNavigate }: { sys: SystemState; onNavigate?: () => void }) {
  const { tone, label } = summarize(sys)
  const Icon = tone === 'ok' ? CircleCheck : tone === 'warn' ? CircleAlert : tone === 'bad' ? CircleX : CircleDashed
  return (
    <Link to="/status" className="sys-indicator" onClick={() => onNavigate?.()}>
      <Icon size={16} className={tone} aria-hidden="true" />
      <span>
        <span className="visually-hidden">System status: </span>
        {label}
      </span>
    </Link>
  )
}

export function summarize(sys: SystemState): { tone: 'ok' | 'warn' | 'bad' | 'unknown'; label: string } {
  if (!sys.health) return sys.healthFailed ? { tone: 'bad', label: 'Server not responding' } : { tone: 'unknown', label: 'Checking system…' }
  if (sys.databaseDown) return { tone: 'bad', label: 'Database unavailable' }
  switch (sys.openai) {
    case 'ok':
      return { tone: 'ok', label: sys.mode === 'demo' ? 'Demo mode · all systems ready' : 'All systems ready' }
    case 'not_configured':
      return { tone: 'warn', label: 'OpenAI not configured' }
    case 'invalid_key':
      return { tone: 'bad', label: 'OpenAI key rejected' }
    case 'unreachable':
      return { tone: 'bad', label: 'OpenAI unreachable' }
    default:
      return { tone: 'warn', label: 'OpenAI error' }
  }
}

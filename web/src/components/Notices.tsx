import { AlertTriangle, DatabaseZap, FlaskConical, KeyRound, Lock } from 'lucide-react'
import { Link } from 'react-router'
import { useAuthRequired } from '../api/queries'
import type { SystemState } from '../lib/system'

/** Global notices above every screen (DESIGN 6.2 "Global"). */
export function Notices({ sys }: { sys: SystemState }) {
  const authRequired = useAuthRequired()
  const openai = sys.openai
  const openaiProblem = !sys.databaseDown && openai && openai !== 'ok'

  return (
    <div className="notices">
      {authRequired && (
        <div className="notice notice-error" role="alert">
          <Lock size={16} aria-hidden="true" />
          <p className="notice-body">
            <strong>Sign-in required.</strong> This workspace is protected by a password.{' '}
            <button type="button" className="linkish" onClick={() => window.location.reload()}>
              Reload the page
            </button>{' '}
            to enter it.
          </p>
        </div>
      )}
      {sys.mode === 'demo' && (
        <div className="notice notice-demo">
          <FlaskConical size={16} aria-hidden="true" />
          <p className="notice-body">
            <strong>Demo mode.</strong> Answers are simulated by a local test service, not written by OpenAI.
            Passages and sources come from your uploaded files.
          </p>
        </div>
      )}
      {sys.databaseDown && (
        <div className="notice notice-error" role="alert">
          <DatabaseZap size={16} aria-hidden="true" />
          <p className="notice-body">
            <strong>Database unavailable.</strong> Documents and conversations cannot be loaded right now. This page
            checks again every few seconds and recovers by itself.
          </p>
        </div>
      )}
      {sys.healthFailed && !sys.health && (
        <div className="notice notice-error" role="alert">
          <AlertTriangle size={16} aria-hidden="true" />
          <p className="notice-body">
            <strong>The app server is not responding.</strong> Check that it is running; this page keeps trying.
          </p>
        </div>
      )}
      {openaiProblem && (
        <div className="notice notice-warn" role="status">
          <KeyRound size={16} aria-hidden="true" />
          <p className="notice-body">
            <strong>{openaiTitle(openai)}</strong> {openaiText(openai)} <Link to="/status">System status</Link>
          </p>
        </div>
      )}
    </div>
  )
}

function openaiTitle(s: string): string {
  switch (s) {
    case 'not_configured':
      return 'OpenAI is not configured.'
    case 'invalid_key':
      return 'OpenAI rejected the API key.'
    case 'unreachable':
      return 'OpenAI cannot be reached.'
    default:
      return 'OpenAI reported an error.'
  }
}

function openaiText(s: string): string {
  switch (s) {
    case 'not_configured':
      return 'Uploading and asking are switched off until OPENAI_API_KEY is set on the server (or demo mode is used). You can still browse.'
    case 'invalid_key':
      return 'Uploads will fail and questions cannot be answered until the key in the server settings is replaced.'
    case 'unreachable':
      return 'Uploads and questions will fail until the connection is back. Check the network of the server.'
    default:
      return 'Uploads and questions may fail. Try again shortly.'
  }
}

// One polite and one assertive live region for status changes (DESIGN 6.4).
import { useSyncExternalStore } from 'react'

type Politeness = 'polite' | 'assertive'
const messages: Record<Politeness, string> = { polite: '', assertive: '' }
const listeners = new Set<() => void>()
let seq = 0

export function announce(text: string, politeness: Politeness = 'polite') {
  // A zero-width suffix that alternates makes repeated identical messages re-announce.
  seq += 1
  messages[politeness] = text + (seq % 2 ? '​' : '')
  listeners.forEach((l) => l())
}

function useMessage(p: Politeness) {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => messages[p],
    () => '',
  )
}

export function LiveRegions() {
  const polite = useMessage('polite')
  const assertive = useMessage('assertive')
  return (
    <>
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {polite}
      </div>
      <div className="visually-hidden" role="alert" aria-live="assertive" aria-atomic="true">
        {assertive}
      </div>
    </>
  )
}

// TESTER: FE-CIT — citations render untrusted text as text, show relevance in plain language,
// mark removed documents, and toggle with aria-expanded (DESIGN 6.2, 6.3, 6.4).
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { Citation } from '../src/api/types'
import { Sources } from '../src/components/Sources'
import { formatRelevance } from '../src/lib/format'
import { highlightSegments, questionTerms } from '../src/lib/highlight'

afterEach(cleanup)

const hostile = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script> vacation days'

function cite(over: Partial<Citation> = {}): Citation {
  return {
    rank: 1,
    document_id: 12,
    document_available: true,
    filename: 'handbook.txt',
    chunk_index: 3,
    similarity: 0.6234,
    text: 'Employees accrue twenty vacation days per year.',
    ...over,
  }
}

describe('Sources / CitationItem', () => {
  it('renders file names and passages as text, never as HTML', () => {
    const { container } = render(
      <Sources citations={[cite({ filename: '<b>evil</b>.txt', text: hostile })]} question="vacation days" />,
    )
    expect(container.querySelector('img, script, b')).toBeNull()
    expect(container.textContent).toContain('<b>evil</b>.txt')
    expect(container.textContent).toContain('<script>')
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined()
  })

  it('shows relevance as a percentage, not a raw float', () => {
    const { container } = render(<Sources citations={[cite()]} question="vacation" />)
    expect(container.textContent).toContain('62% match')
    expect(container.textContent).not.toContain('0.6234')
  })

  it('orders by rank and opens only the first passage; toggles with aria-expanded', () => {
    render(
      <Sources
        citations={[cite({ rank: 2, filename: 'second.md', text: 'Second passage' }), cite({ rank: 1, text: 'First passage' })]}
        question="passage"
      />,
    )
    const toggles = screen.getAllByRole('button')
    expect(toggles).toHaveLength(2)
    expect(toggles[0]!.textContent).toContain('handbook.txt')
    expect(toggles[0]!.getAttribute('aria-expanded')).toBe('true')
    expect(toggles[1]!.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(toggles[1]!)
    expect(toggles[1]!.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText(/Second/)).toBeTruthy()
    fireEvent.click(toggles[0]!)
    expect(toggles[0]!.getAttribute('aria-expanded')).toBe('false')
  })

  it('marks a citation whose document was removed, keeping the passage', () => {
    const { container } = render(
      <Sources citations={[cite({ document_id: null, document_available: false, chunk_index: null })]} question="x" />,
    )
    expect(container.textContent).toMatch(/removed/i)
    expect(container.textContent).toContain('Employees accrue twenty vacation days per year.')
  })
})

describe('format and highlight helpers', () => {
  it.each([
    [0, '0% match'],
    [0.3049, '30% match'],
    [1, '100% match'],
    [1.2, '100% match'],
    [-0.1, '0% match'],
  ])('formatRelevance(%s) = %s', (sim, out) => {
    expect(formatRelevance(sim)).toBe(out)
  })

  it('highlight keeps the full text and marks whole words only', () => {
    const text = 'Vacation days: vacationing is not vacation.'
    const segs = highlightSegments(text, questionTerms('How many vacation days?'))
    expect(segs.map((s) => s.text).join('')).toBe(text)
    const marked = segs.filter((s) => s.marked).map((s) => s.text)
    expect(marked).toContain('Vacation days')
    expect(marked.join(' ')).not.toContain('vacationing')
  })
})

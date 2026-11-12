import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { seriousViolations } from '../test/axe'
import { renderApp } from '../test/render'

afterEach(() => vi.unstubAllGlobals())

const CONV = '/c/5b0a3c1e-7c59-4d0e-9a55-0c9d5f3a2b11'

describe('Workspace and composer', () => {
  it('shows readiness and asks a question, then shows the cited answer', async () => {
    const user = userEvent.setup()
    const { router } = renderApp('/')
    expect(await screen.findByText(/ready to search/)).toBeInTheDocument()
    const box = await screen.findByLabelText('Your question')
    await waitFor(() => expect(box).toBeEnabled())
    await user.type(box, 'How many vacation days?{Enter}')
    expect(await screen.findByText(/Simulated answer/)).toBeInTheDocument()
    expect(router.state.location.pathname).toMatch(/^\/c\//)
    const sources = screen.getByRole('region', { name: /Sources \(1\)/ })
    expect(within(sources).getByText('employee-handbook-2026.pdf')).toBeInTheDocument()
    expect(within(sources).getByText('62% match')).toBeInTheDocument()
    // First source is open with the question's words highlighted.
    const marks = sources.querySelectorAll('mark')
    expect([...marks].map((m) => m.textContent)).toEqual(expect.arrayContaining(['days', 'vacation']))
  })

  it('Shift+Enter makes a new line instead of sending', async () => {
    const user = userEvent.setup()
    const { fetchMock } = renderApp('/')
    const box = await screen.findByLabelText('Your question')
    await waitFor(() => expect(box).toBeEnabled())
    await user.type(box, 'line one{Shift>}{Enter}{/Shift}line two')
    expect(box).toHaveValue('line one\nline two')
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/messages'))).toBe(false)
  })

  it('is disabled with a reason when no document is ready', async () => {
    renderApp('/', { documents: [] })
    expect(await screen.findByText('Start by adding documents')).toBeInTheDocument()
    expect(screen.getByLabelText('Your question')).toBeDisabled()
    expect(screen.getByText(/Upload at least one document/)).toBeInTheDocument()
  })

  it('is disabled with a reason when OpenAI is not configured', async () => {
    renderApp('/', { openai: 'not_configured', mode: 'live' })
    expect(await screen.findByText(/OpenAI is not configured\. Add OPENAI_API_KEY/)).toBeInTheDocument()
    expect(screen.getByLabelText('Your question')).toBeDisabled()
  })

  it('shows a failure inline, keeps the question, and retries', async () => {
    const user = userEvent.setup()
    renderApp(CONV, {
      nextAskError: { status: 503, code: 'openai_rate_limited', message: 'OpenAI is busy. Try again in a minute.' },
    })
    const box = await screen.findByLabelText('Your question')
    await waitFor(() => expect(box).toBeEnabled())
    await user.type(box, 'What about carry-over?{Enter}')
    expect(await screen.findByText('OpenAI is busy. Try again in a minute.')).toBeInTheDocument()
    expect(box).toHaveValue('What about carry-over?')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText(/Simulated answer/)).toBeInTheDocument()
  })

  it('marks an answer that is not grounded and shows no sources', async () => {
    const user = userEvent.setup()
    renderApp(CONV)
    const box = await screen.findByLabelText('Your question')
    await waitFor(() => expect(box).toBeEnabled())
    await user.type(box, 'What is the weather tomorrow?{Enter}')
    expect(await screen.findByText('Not found in your documents')).toBeInTheDocument()
    expect(screen.getAllByRole('region', { name: /Sources/ })).toHaveLength(1) // only the earlier answer
  })
})

describe('Conversation thread and citations', () => {
  it('opens and closes a passage; removed sources are labelled', async () => {
    const user = userEvent.setup()
    renderApp(CONV)
    await screen.findByText('leave-policy-2025.md')
    const second = screen.getByRole('button', { name: /Source 2:\s*leave-policy-2025\.md/ })
    expect(second).toHaveAttribute('aria-expanded', 'false')
    expect(within(second).getByText(/Removed from library/)).toBeInTheDocument()
    await user.click(second)
    expect(second).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(/has since been deleted/)).toBeInTheDocument()
    await user.click(second)
    expect(second).toHaveAttribute('aria-expanded', 'false')
  })

  it('shows a not-found state for an unknown conversation', async () => {
    renderApp('/c/00000000-0000-4000-a000-000000000000')
    expect(await screen.findByText('This conversation does not exist')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Start a new conversation' })).toBeInTheDocument()
  })

  it('renames and deletes a conversation with confirmation', async () => {
    const user = userEvent.setup()
    const { router } = renderApp(CONV)
    await user.click(await screen.findByRole('button', { name: 'Rename conversation' }))
    const input = screen.getByLabelText('Conversation title')
    await user.clear(input)
    await user.type(input, 'Vacation rules{Enter}')
    expect(await screen.findByRole('heading', { level: 1, name: 'Vacation rules' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Delete conversation' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Delete “Vacation rules”?')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Delete conversation' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })
})

describe('Library', () => {
  it('lists documents with status, size and failure reason', async () => {
    renderApp('/library')
    const table = await screen.findByRole('table')
    expect(within(table).getByText('employee-handbook-2026.pdf')).toBeInTheDocument()
    expect(within(table).getAllByText('Ready')).toHaveLength(2)
    expect(within(table).getByText('Failed')).toBeInTheDocument()
    expect(within(table).getByText(/Remove it and upload it again/)).toBeInTheDocument()
    expect(within(table).getByText('471 KB')).toBeInTheDocument()
  })

  it('uploads files one by one, shows processing, then ready without reload', async () => {
    const user = userEvent.setup()
    renderApp('/library', { pollsUntilReady: 0 })
    const input = document.getElementById('file-input') as HTMLInputElement
    await screen.findByRole('table')
    await user.upload(input, [new File(['hello policy'], 'notes.txt', { type: 'text/plain' })])
    const row = (await screen.findByText('notes.txt')).closest('tr')!
    expect(within(row).getByText(/Indexing|Ready/)).toBeInTheDocument()
    await waitFor(() => expect(within(row).getByText('Ready')).toBeInTheDocument(), { timeout: 4000 })
  })

  it('shows the specific rejection message per file', async () => {
    const user = userEvent.setup()
    renderApp('/library', {
      nextUploadError: { status: 400, code: 'invalid_encoding', message: 'The file is not UTF-8 text. Save it as UTF-8 and upload it again.' },
    })
    await screen.findByRole('table')
    const input = document.getElementById('file-input') as HTMLInputElement
    await user.upload(input, [new File(['\xff\xfe'], 'latin1.txt', { type: 'text/plain' })])
    expect(await screen.findByText(/Not uploaded: The file is not UTF-8 text/)).toBeInTheDocument()
  })

  it('blocks uploads when OpenAI is not configured', async () => {
    renderApp('/library', { openai: 'not_configured', mode: 'live' })
    await screen.findByRole('table')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Choose files' })).toBeDisabled())
  })

  it('shows the empty state', async () => {
    renderApp('/library', { documents: [] })
    expect(await screen.findByText('No documents yet')).toBeInTheDocument()
  })

  it('confirms deletion naming the document and the kept passages', async () => {
    const user = userEvent.setup()
    renderApp('/library')
    await user.click(await screen.findByRole('button', { name: 'Delete employee-handbook-2026.pdf' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Delete “employee-handbook-2026.pdf”?')).toBeInTheDocument()
    expect(within(dialog).getByText(/keep the passages they quoted/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Delete document' }))
    await waitFor(() => expect(screen.queryByText('employee-handbook-2026.pdf')).not.toBeInTheDocument())
  })
})

describe('Global states', () => {
  it('always shows the demo notice in demo mode', async () => {
    renderApp('/status')
    expect(await screen.findByText('Demo mode.')).toBeInTheDocument()
  })

  it('shows the database-unavailable state', async () => {
    renderApp('/library', { database: 'unavailable' })
    expect(await screen.findByText('Database unavailable.')).toBeInTheDocument()
    expect(await screen.findByText('The document list could not be loaded')).toBeInTheDocument()
  })

  it('status screen shows components and limits', async () => {
    renderApp('/status', { openai: 'invalid_key', mode: 'live' })
    expect(await screen.findByText('Key rejected')).toBeInTheDocument()
    expect(screen.getByText('Available')).toBeInTheDocument()
    expect(await screen.findByText('20 MB per file')).toBeInTheDocument()
  })

  it('not found route offers a way back', async () => {
    renderApp('/no-such-page')
    expect(await screen.findByRole('link', { name: 'Back to the workspace' })).toBeInTheDocument()
  })
})

describe('Accessibility (axe, serious and critical)', () => {
  it.each(['/', CONV, '/library', '/status', '/nope'])('%s has no serious violations', async (path) => {
    renderApp(path)
    await screen.findAllByRole('heading', { level: 1 })
    await waitFor(() => expect(document.querySelector('[aria-busy="true"]')).toBeNull())
    expect(await seriousViolations()).toEqual([])
  })
})

import { describe, expect, it } from 'vitest'
import { formatBytes, formatRelevance } from './format'
import { highlightSegments, questionTerms } from './highlight'

describe('highlight', () => {
  it('keeps content words of the question', () => {
    expect(questionTerms('How many vacation days do full-time employees get?')).toEqual([
      'many',
      'vacation',
      'days',
      'full',
      'time',
      'employees',
      'get',
    ])
  })

  it('marks whole words only, case-insensitively, and joins adjacent marks', () => {
    const segs = highlightSegments('Paid Vacation days. Vacationing is different.', ['vacation', 'days'])
    expect(segs.filter((s) => s.marked).map((s) => s.text)).toEqual(['Vacation days'])
    expect(segs.map((s) => s.text).join('')).toBe('Paid Vacation days. Vacationing is different.')
  })

  it('returns the text untouched without terms', () => {
    expect(highlightSegments('<b>x</b>', [])).toEqual([{ text: '<b>x</b>', marked: false }])
  })
})

describe('format', () => {
  it('shows relevance as a percentage, not a raw float', () => {
    expect(formatRelevance(0.6214)).toBe('62% match')
  })
  it('formats sizes', () => {
    expect(formatBytes(null)).toBe('—')
    expect(formatBytes(482_133)).toBe('471 KB')
    expect(formatBytes(20 * 1024 * 1024)).toBe('20 MB')
  })
})

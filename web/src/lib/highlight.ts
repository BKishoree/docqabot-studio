// Marks the words of a question inside a passage, the "highlighter" of the UI.
// Pure text processing: returns segments, rendered as React text nodes (never HTML).

const STOP_WORDS = new Set(
  (
    'a an and are as at be but by can could did do does for from had has have how i if in into is it its ' +
    'me my no not of on or our so such than that the their them then there these they this those to ' +
    'was we were what when where which who whom why will with would you your about any all also'
  ).split(' '),
)

export interface Segment {
  text: string
  marked: boolean
}

/** Content words of the question, lower-cased, at least 3 characters (or digits). */
export function questionTerms(question: string): string[] {
  const words = question.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []
  const terms = new Set<string>()
  for (const w of words) {
    if (STOP_WORDS.has(w)) continue
    if (w.length < 3 && !/^\p{N}+$/u.test(w)) continue
    terms.add(w)
  }
  return [...terms]
}

/** Split `text` into segments; whole words that match a term are `marked`. */
export function highlightSegments(text: string, terms: string[]): Segment[] {
  if (terms.length === 0 || text.length === 0) return [{ text, marked: false }]
  const wanted = new Set(terms)
  const segments: Segment[] = []
  const re = /[\p{L}\p{N}]+/gu
  let last = 0
  let match: RegExpExecArray | null
  const push = (t: string, marked: boolean) => {
    if (!t) return
    const prev = segments[segments.length - 1]
    if (prev && prev.marked === marked) prev.text += t
    else segments.push({ text: t, marked })
  }
  while ((match = re.exec(text)) !== null) {
    const word = match[0]
    const isMarked = wanted.has(word.toLowerCase())
    push(text.slice(last, match.index), false)
    push(word, isMarked)
    last = match.index + word.length
  }
  push(text.slice(last), false)
  // Join marks separated only by a single space so a phrase reads as one stroke.
  const merged: Segment[] = []
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]!
    const prev = merged[merged.length - 1]
    const next = segments[i + 1]
    if (!seg.marked && (seg.text === ' ' || seg.text === '-') && prev?.marked && next?.marked) {
      prev.text += seg.text + next.text
      i++
      continue
    }
    if (seg.marked && prev?.marked) {
      prev.text += seg.text
      continue
    }
    merged.push({ ...seg })
  }
  return merged
}

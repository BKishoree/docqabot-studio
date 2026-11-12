# DocQABot Studio web: design notes

Written by the frontend engineer, 2026-11-12. Required by DESIGN.md F1 and AC21. All values below are in `src/styles/tokens.css` and used through CSS custom properties only.

## Direction: "highlighted photocopy"

The people using this are analysts and operations leads checking answers against their own policies, contracts and handbooks. The page should look like the reviewer's desk, not an AI chat tool: a photocopied page, a highlighter, a red and a blue pen, and a dark binder spine.

- **Thesis.** The answer is the summary; the highlighted passage is the evidence. Answers are not chat bubbles. Each answer is followed by a ranked SOURCES list, the passages are set like quoted document text, and the words of the question are marked with a highlighter.
- **What was refused.** Purple/indigo/blue gradients, the default shadcn slate+violet, glassy or neon chat looks, sparkle "AI" branding, chat bubbles, avatar icons (owner's direction).
- **How it was chosen.** The `impeccable` skill rolled seven grounded worlds from the audience's own surroundings (legal exhibit tabs, archive finding aids, annotated statute books, case-file folders, standards documents, ledgers, the highlighted photocopy). The roll assigned candidate 7 (seed reference `seed:f6845ef62429a18e`). It was presented to the owner next to "exhibit tabs", an "acetate tab manual" challenger and the category standard, and the owner chose "highlighted photocopy".
- **Raises borrowed from challengers.** From *Japanese high-density web*: a strict 1px hairline system and a denser library table. From *acetate tab manual*: short, stepped motion with no floaty easing.

## Colour (Restrained, tinted from the world)

| Token | Value | Job |
| --- | --- | --- |
| `--paper` | `#f5f6f4` | Work-area ground: cool photocopy white, deliberately not cream |
| `--sheet` | `#ffffff` | Raised surfaces: composer, table, passages, dialogs |
| `--ink` / `--ink-2` / `--ink-3` | `#1a1c1e` / `#4d5459` / `#646b70` | Text: 16.4:1, 7.3:1 and 5.2:1 on paper (all pass AA) |
| `--rail` | `#23282b` | Graphite rail (the binder spine); rail text `#eceeeb`, secondary `#a9b0b4` (6.9:1) |
| `--mark` | `#ffe45c` | **Highlighter.** Means only "quoted evidence" or "you are here" (active nav item, wordmark, selection). Always paired with ink text. |
| `--pen-blue` | `#1f47b8` | Links, focus ring, primary action, source rank numbers (7.5:1) |
| `--pen-red` | `#b3261e` | Errors and destructive actions (6.1:1) |
| `--green` / `--amber` | `#276b3c` / `#8a5a00` | Ready / indexing status text on soft tints |

Status is never shown by colour alone: every pill has an icon and a word (Ready, Indexing, Failed, Available, Key rejected…).

## Type

- **Interface: Public Sans** (400/500/600/700), a neutral workhorse from public-sector document design. It has tabular figures, which the tables and sizes use (`font-variant-numeric: tabular-nums`).
- **Quoted passages: Source Serif 4** (400/600). Serif marks "this is the document speaking", so a passage cannot be mistaken for the model's answer. Passages use 1rem/1.65.
- Both fonts are self-hosted through `@fontsource/*` npm packages and bundled into `dist/assets`. Nothing loads from a third-party host.
- Scale: 12 / 13 / 15 (body) / 17 / 22 / 28 px. Section labels are 12px uppercase with +0.06–0.08em tracking. Headings use -0.015em.

## Layout

- Desktop: a fixed 272px graphite rail (wordmark, Ask / Library / Status, conversation list, system indicator) and the work column. The reading column is at most 760px wide; the library and status pages go up to 1120px.
- The composer is docked to the bottom of the thread (sticky). Enter sends, Shift+Enter adds a line.
- Below 860px the rail becomes a slide-in drawer (menu button, scrim, Escape closes, focus moves in and back). The document table reflows into stacked records with labels. Checked at 360px: no horizontal scroll.
- Radii: 6px (4px on small controls); pills only for status. Elevation is declared once: a soft shadow on the composer and dialogs, hairlines everywhere else, no nested cards.

## Signature: the highlighter

`src/lib/highlight.ts` takes the content words of the question (stop words removed) and marks whole-word matches in each passage with `<mark>`. It joins marks across single spaces and hyphens so a phrase reads as one stroke. The mark is drawn as a band (12%–90% of the line), like a real highlighter. The heading says "Highlighted: words from your question", so the highlight never claims more than it is. All text is rendered as React text nodes and never as HTML.

## Motion (from `emil-design-eng`)

- Short and purposeful only: button press `scale(0.97)` (120ms), drawer slide 220ms, dialog `scale(0.97)`→1 (180ms), citation chevron rotation. Easing `cubic-bezier(0.23, 1, 0.32, 1)`; no ease-in anywhere.
- The "writing the answer" indicator is three highlighter bars with a stepped (not eased) blink.
- No animation on keyboard-driven actions or list changes. `prefers-reduced-motion` turns animation and transitions off and stops the spinners.

## Skills used

- `impeccable`: context load, direction roll (`concept-seed`), craft-floor checklist, and the design detector (`impeccable detect`). The detector flagged one tell, a 3px stripe on the active conversation; it was replaced with a faint highlighter wash. Final run: no findings.
- `emil-design-eng`: motion decisions (what animates, durations, easing, press feedback, reduced motion).
- `21st-components`: not used; every component is small and custom so it stays within this world.

## Deviations from the impeccable flow (stated honestly)

- The direction was presented with the in-chat question tool, not impeccable's decision web page, to save memory on this laptop.
- No separate finish-reviewer subagent ran. The critique was an in-thread pass: I looked at the screens at 1440px and 360px against the direction, ran the detector, and fixed what I found (wordmark band looked like strike-through, empty band above content on mobile, oversized phone composer, hyphenated highlight gaps, the stripe).
- The durable design record is this file, as DESIGN.md asks, not an impeccable `DESIGN.md`.

# Product

<!-- impeccable:product-schema 1 -->

> Written by the frontend engineer (subagent, no interview channel). Every fact below comes from
> `docs/DESIGN.md` (architect, v1) and the orchestrator's brief; nothing was confirmed in a live
> interview. Lines marked (inferred) are interpretation, not owner statements.

## Platform

web

## Stack

React + Vite + TypeScript, React Router, TanStack Query (fixed by docs/DESIGN.md section 3).
Styling and visual decisions delegated to the frontend engineer.

## Users

One person or one small trusted team sharing one workspace: an analyst, operations lead or
consultant who needs answers out of a pile of policies, contracts, reports or manuals and must be
able to show where each answer came from. They are not developers and never see a terminal after
the app is started.

## Product Purpose

Upload PDF, Markdown or text files, wait until they are indexed, ask questions in plain language,
and get an answer together with the exact passages it was drawn from. Conversations are kept so
the person can come back to them. Success: the person can check every answer against its source
passage without leaving the screen.

## Positioning

The answer is never the end product; the cited passage is. Each answer carries up to five ranked
passages with their relevance, quoted as stored at answer time, which survive deletion of the
source document. Answers with no supporting passage are marked as not grounded.

## Operating Context

- Runs on a laptop (127.0.0.1) or a closed server; must work fully offline apart from OpenAI.
- Demo mode uses a local stub: every screen must say answers are simulated.
- Degraded states are normal operating conditions: OpenAI key missing/invalid/unreachable,
  database unavailable, documents failing to process.

## Capabilities and Constraints

- Library: upload (PDF/MD/TXT, 20 MB default), status processing/ready/failed, delete.
- Conversations: create on first question, list, open, rename, delete. No streaming.
- Answers are plain text; no Markdown rendering. File names and passages are untrusted text.
- No user accounts; optional HTTP Basic gate via browser prompt.
- No third-party runtime resources (fonts bundled, no CDN, no analytics).

## Brand Commitments

- Owner direction (relayed by orchestrator): must not look like the generic AI-tool palette (no
  purple/indigo-to-blue gradients, no default shadcn slate+violet, no glassy neon chat-bot look,
  no emoji-sparkle "AI" branding). A business document workspace: calm, legible, trustworthy,
  information-dense where it helps, citations first-class.
- Light theme required; dark theme optional.

## Evidence on Hand

None. No customers, logos, testimonials or real documents. Demo content shown during development
is synthetic and comes from `src/mocks/`.

## Product Principles

1. Sources over prose: the passage is as prominent as the answer.
2. Say what is wrong and what to do next, in plain words, from the API's `error.message`.
3. Never hide a degraded state; never block browsing because of it.
4. Calm under load: density is allowed, decoration is not.

## Accessibility & Inclusion

WCAG 2.1 AA, full keyboard operation, live-region announcements, reduced motion, 360 px to 1920 px.

---
name: Presentation File Architecture
description: How index.html, slides.js, glossary.js, and engine.js interact in the educational presentation
type: project
---

# Presentation File Architecture

Location: `docs/educational-readme/presentation/`

## Load Order (index.html)

```html
<script src="slides.js"></script>    <!-- 1st: defines SLIDES global -->
<script src="glossary.js"></script>  <!-- 2nd: defines GLOSSARY global -->
<script src="engine.js"></script>    <!-- 3rd: reads both, builds the DOM -->
```

Order is critical. engine.js reads SLIDES and GLOSSARY at startup. They must exist before it runs.

## slides.js

**What it does:** Defines the `SLIDES` global object — the entire content of the presentation.

**Structure:**
```js
const SLIDES = {
  meta: { totalChapters: 14 },
  sections: [ /* array of slide objects, in render order */ ]
}
```

Each slide object has:
- `id` — unique string, used as DOM id (`slide-{id}`)
- `layout` — one of: `hero`, `chapter-title`, `center-text`, `comparison`, `diagram`, `diagram-only`, `roadmap`
- `chapter` — integer, only on `chapter-title` slides; engine propagates it to all subsequent slides
- `title`, `body`, `subtitle`, `caption`, `notes`, `diagram` — layout-specific fields

**Key rules:**
- Physical array order in `sections` is the render order. Filenames don't matter.
- `chapter:` integer on chapter-title slides controls what "Chapter N of 14" displays.
- `body` and `caption` text supports `**bold**` and `[[Glossary Term]]` syntax — engine parses both.
- `notes` is plain text only — displayed in speaker notes panel (N key), not parsed for markup.
- Diagrams are referenced by name string (e.g., `diagram: 'agent-loop'`). All diagram renderers live in engine.js.

**Slide IDs vs chapter numbering:**
After the chapter reorder, slide IDs no longer match chapter numbers (e.g., `id: 'ch4-title'` is now chapter 10). The `chapter:` field in each chapter-title slide is the authoritative number. Don't trust the `id` prefix.

## glossary.js

**What it does:** Defines the `GLOSSARY` global object — a lookup table of terms to popup content.

**Structure:**
```js
const GLOSSARY = {
  'Term Name': {
    title: 'Display Title',
    description: 'One-sentence summary shown in popup header.',
    code: `...full code or text content...`,
    language: 'python' | 'json' | 'text' | 'markdown'
  },
  ...
}
```

**Two categories of entries:**
1. Technical terms (`YAML frontmatter`, `tool schema`, `JSONL`, etc.) — code snippets showing patterns
2. Demo prompts (`Demo Prompt: Chapter 1` through `Demo Prompt: Chapter 10`) — full prompt text, `language: 'text'`

**How a term becomes clickable in a slide:**
Write `[[Term Name]]` in a slide's `body` or `caption` field in slides.js. Engine converts it to a `<span class="glossary-term" data-glossary-key="Term Name">`. If the key doesn't exist in GLOSSARY, it renders as plain text (no crash, just no popup).

**Syntax rules (critical):**
- Every entry except the last must end with `},` (comma)
- The last entry before `};` has no trailing comma
- A stray `};` anywhere inside the object closes it early — all entries after are orphaned JS syntax errors (this bug existed at line 584 and was fixed 2026-05-19)

**Current entries (20 total):**
- 10 technical terms
- Demo Prompt: Chapter 1 through Demo Prompt: Chapter 10

## engine.js

**What it does:** Reads SLIDES and GLOSSARY, builds the entire DOM, wires all interactivity. Zero external dependencies — pure vanilla JS wrapped in an IIFE.

**Startup sequence (init()):**
1. `buildPresentation(SLIDES)` — iterates sections array, creates a `<section>` DOM element for each slide
2. `applyStaggerDelays()` — sets CSS transition delays on `[data-order]` elements for staggered animation
3. `setupObserver()` — IntersectionObserver fires when a slide enters the viewport → adds `.visible` class → triggers CSS animations; also updates current slide index, speaker notes
4. `setupNavigation()` — keyboard handlers: Arrow keys / Space = next/prev slide, N = notes, G = chapter nav, F = fullscreen, Home/End = first/last
5. `setupProgressBar()` — scroll listener updates thin bar at top
6. `buildChapterNav(SLIDES)` — builds the G-key overlay by scanning for `layout: 'chapter-title'` slides with `chapter != null`
7. `setupGlossaryPopups()` — event delegation on `document` for `.glossary-term` clicks; creates one shared popup element; wires copy button

**Layout builders** (one per layout type):
- `buildHero` — title + subtitle + scroll hint
- `buildChapterTitle` — chapter number + heading + subtitle (no body text)
- `buildCenterText` — title + body (parsed with formatText)
- `buildComparison` — title + two-column list (items parsed with formatInline)
- `buildDiagram` — title + body + SVG diagram
- `buildDiagramOnly` — title + caption + big SVG diagram (no body)
- `buildRoadmap` — title + body + timeline items

**Text parsing pipeline:**
```
slides.js body/caption string
  → formatText() / formatInline()
    → escAndFormat()
      1. Extract [[Term]] placeholders BEFORE HTML-escaping
      2. HTML-escape everything else (&, <, >)
      3. Apply **bold** → <strong>
      4. Re-insert [[Term]] as <span class="glossary-term" data-glossary-key="Term">
         (only if GLOSSARY[term] exists; otherwise plain escaped text)
```

`notes` fields bypass all of this — rendered with `esc()` only (plain text in the notes panel).

**Diagram system:**
- `renderDiagram(name)` dispatches to a named renderer function
- All renderers return SVG strings built with string concatenation (no external SVG files)
- `[data-order]` attributes on SVG elements control staggered animation via `applyStaggerDelays()`
- To add a new diagram: add a renderer function and register it in the `renderers` dict inside `renderDiagram()`

**Chapter tracking:**
- engine.js tracks `currentChapter` during `buildPresentation()` — it updates when it encounters a `chapter-title` slide
- Each section gets `section._chapter = currentChapter` so the chapter indicator always knows where you are
- `buildChapterNav()` builds the G-key overlay from chapter-title slides only (not all slides)

## How the [[Demo Prompt]] Flow Works End-to-End

1. Author writes `[[Demo Prompt: Chapter 6]]` in a slide's `body` in slides.js
2. Engine's `escAndFormat()` extracts `Demo Prompt: Chapter 6` before HTML-escaping
3. It checks `GLOSSARY['Demo Prompt: Chapter 6']` — finds it
4. Renders: `<span class="glossary-term" data-glossary-key="Demo Prompt: Chapter 6">Demo Prompt: Chapter 6</span>`
5. User clicks the span → `setupGlossaryPopups()` handler fires
6. Builds popup: title, description, full prompt text in `<pre><code>`, Copy button
7. Copy button calls `navigator.clipboard.writeText(entry.code)` — copies the full prompt
8. Presenter pastes directly into a ClarAIty session to run the live demo

## What NOT to Edit in engine.js

- The `renderers` dict in `renderDiagram()` — only add, never rename existing keys (slide data references by name)
- The `escAndFormat()` function — the placeholder extraction order is load-bearing
- The `buildChapterNav()` logic — it relies on `layout === 'chapter-title'` and `chapter != null` being present
- The script load order in index.html — engine.js must be last

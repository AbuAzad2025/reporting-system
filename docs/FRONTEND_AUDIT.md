# Front-end audit

Every number below is measured from the repository, not estimated. The
measurements that matter are re-checked on each run by
`tests/test_template_css_contract.py` (16 tests) and `tests/theme.test.js`
(18 vitest tests), so this document cannot drift away from the code without a
test failing.

Last audited: 2026-09-28.

## What this application actually is

It is a Jinja server-rendered application. There is no SPA, no client-side
router, no state library and no build step. That is a deliberate shape, and it
is the right one for a system whose data is relational and whose users are on
office networks.

| Asset | Count | Size |
| --- | --- | --- |
| Templates | 31 | 136,512 B |
| Stylesheets | 2 | 65,553 B |
| JavaScript | 2 modules under `static/js` | 9,778 B |
| Service worker | 1 (`static/sw.js`) | — |
| Client-side dependencies | 1 (vitest, dev only) | — |

29 of the 31 templates extend `base.html`. The two that do not are `base.html`
itself and `_macros.html`, which is a partial and not a page.

The practical consequence: **the front end's behaviour lives in CSS, in Jinja,
and in under 10 KB of JavaScript.** There is very little JavaScript to test,
and everything else is testable by asserting on the rendered markup.

## Findings

### 1. A third of the CSS the application used simply did not exist — fixed

The templates referenced 341 distinct class names. 269 of them were not defined
in any stylesheet, and they appeared 2,090 times across the templates. Markup
was written expecting a component library that the project did not have:
`subsection-heading`, `form-actions`, `inline-actions`, `data-table`,
`stat-grid`, and so on.

Nothing looked broken in a code review, and nothing crashed. The pages simply
rendered unstyled blocks with default margins and no visual hierarchy, so
"it looks off" was the only symptom and it had no cause anyone could name.

Resolved by writing the missing layer as `static/css/utilities.css` (25,724 B)
and loading it from `base.html`.

| | Before | After |
| --- | --- | --- |
| Undefined classes | 269 | **0** |
| Undefined occurrences | 2,090 | **0** |
| Defined classes | — | 646 |

This is now enforced. A test walks every `class="..."` in every template and
fails if any name is not defined in CSS, so the gap cannot reopen.

### 2. The dark mode toggle did not do anything — fixed

The stylesheet scoped the dark theme to `.dark`, a class. The toggle in
`base.html` set `data-theme="dark"`, an attribute. No rule anywhere matched
the value the UI produced, so the switch flipped and the page stayed light.

The two halves disagreed, both were internally reasonable, and no test could
see it: the CSS test checked that *a* dark selector existed, and the template
test checked that the toggle set *an* attribute. Neither checked that they
were the same one.

Fixed in two steps. The stylesheet now honours `[data-theme="dark"]` (keeping
`.dark` working as well), and the theme logic was extracted from an inline
`<script>` into `static/js/theme.js`.

The first test in `tests/theme.test.js` reads the stylesheet and the module
and asserts they agree on the attribute name. That is the test that would have
caught this, and it now fails if the two ever drift apart again.

### 3. Form controls were styled by hand, 26 different ways — fixed

`tests/test_template_css_contract.py` found 56 inputs styled as ad-hoc CSS
rather than as controls, across 35 different class-name spellings. The same
text input was styled one way in one form and another way three forms later.

Replaced with `.form-control`, defined in `custom.css` and applied through the
macros in `templates/_macros.html`:

| | Count |
| --- | --- |
| User-facing inputs | 94 |
| In the control family | **94** |
| Of which `.form-control` | 93 |
| Of which `.form-control-file` | 1 |
| Hidden / choice inputs | 26 |

The file input is deliberately not a `.form-control`. That rule sets
`appearance: none`, which strips the native "choose file" button and leaves a
control that looks broken. It carries `.form-control-file` instead, which
keeps the native button, restyles it with `::file-selector-button`, and matches
the rest of the family's border, padding and focus ring. A test now fails if
any user-facing control drifts out of the family.

### 4. Labels were decorative — fixed

53 form fields had a `<label>` that was not connected to its control, so
clicking the label did not focus the input and screen readers got no
accessible name.

Now bound with `for`/`id` or given an `aria-label`.

| | Count |
| --- | --- |
| Bound with `for`/`id` | 59 |
| Named with `aria-label` | 35 |
| **Unlabelled** | **0** |

### 5. Cards were written out five different ways — fixed

29 card-like blocks each spelled out their own padding, border and shadow
instead of using a shared surface. Replaced with `.surface-card`.

### 6. Nothing tested the JavaScript — fixed

This was the largest real gap. The previous CI step ran `node --check`, which
parses a file without executing it, and then:

```sh
node --check static/js/app.js || echo "::warning::JS syntax note (optional, does not fail CI)"
```

A syntax error printed a warning and the job still passed. The check was
decorative: a completely broken script reached production behind a green
build. Node was also optional, so the step could skip itself entirely.

Replaced with:

- `tests/theme.test.js` — 18 vitest tests that execute the theme logic against
  fake DOM, storage and `matchMedia` objects. They cover the stored-preference
  beats the system-preference case, the toggle writes `dark` on and `light` on
  off, both are persisted, a chosen dark theme survives a reload, and storage
  that throws (private browsing, exhausted quota) degrades instead of breaking
  the page. One test reads the stylesheet and the module and asserts they
  agree on the theme attribute, so the two halves cannot drift apart again.
- A syntax step that **fails** on a missing Node, or on any of the three
  JavaScript files, rather than warning and continuing.
- A `Frontend Tests` job running `npx vitest run` in CI, alongside the
  existing `frontend-syntax-check` job. That makes 13 jobs.

The theme logic had to be extracted from an inline `<script>` to be testable at
all. Inline script in a template cannot be imported by a test, so the code that
had the bug was the code no test could reach.

### 7. The service worker was never cache-busted

Not a defect, but worth recording because the next person will trip over it.
`base.html` registered the worker at a hard-coded `/static/sw.js`, bypassing
`asset_url()`. Every other asset in the project is cache-busted, so this one
was the exception: a new service worker was not picked up until the browser
was left to expire the old one on its own.

It now registers through `asset_url('sw.js')`, which yields the same
`/static/sw.js` path with a version query string. The path deliberately stays
the same: changing it would register a second worker under a different script
URL, and the old one would keep serving the old cache.

## Cross-cutting media and motion support

All present, and covered by the CSS contract test:

- `prefers-reduced-motion` — animations are suppressed for users who ask.
- `:focus-visible` — keyboard focus is visible without a focus ring on
  mouse clicks.
- `@media print` — reports print cleanly.

## Accessibility beyond labels

Checked and adequate: the toast container is `aria-live="polite"`, so
transient messages are announced without stealing focus. Hidden inputs are
used for state rather than `display:none` on visible ones. Colour is carried by
CSS custom properties (114 of them), which is what makes the dark theme and the
`prefers-reduced-motion` path a matter of changing values rather than
rewriting rules.

Not verified, and I want to be explicit about it: **no screen-reader testing and
no automated axe scan was run.** A static analyser would find missing names and
bad contrast, but it cannot tell you whether a table actually makes sense when
read aloud. That needs a human with a screen reader, and it is listed as open
work rather than claimed as done.

## What the tests do and do not prove

They do prove, on every CI run:

- every class used in a template is defined in CSS
- every template is translated, and its blocks balance
- no template contains malformed or spliced Jinja tags
- every user-facing control has an accessible name
- the theme attribute written by JavaScript matches the one the CSS reads
- theme preference, persistence and degraded storage behave as specified
- every JavaScript file parses

They do not prove anything about how any of it looks, because nothing here
measures rendered pixels. And they cannot catch a CSS rule that is valid,
defined, and wrong.

## Open work

| Item | Status |
| --- | --- |
| Screen-reader pass with NVDA or VoiceOver | Not done. Needs a human. |
| Contrast ratios measured in both themes | Not measured. Current rules were not checked against WCAG AA. |
| Visual regression against rendered pages | No baseline images; no browser automation in the project. |
| RTL layout | The application is Arabic. Only logical CSS properties were used when writing `utilities.css`; whether every direction assumption is safe is unverified. |
| `::file-selector-button` in Safari and Firefox | The file input styling is the newest rule here and has not been opened in a real browser. |

Nothing in this table is claimed as fixed, and none of it is a defect the test
suite would catch. They are the limits of what static checks can tell you.

## Reproducing the measurements

```sh
python -m pytest tests/test_template_css_contract.py -q   # 16 tests
npx vitest run                                            # 18 tests
```

The inventory, undefined-class count, label and control counts in this document
are the same numbers those two suites assert on.

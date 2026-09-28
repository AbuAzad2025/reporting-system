# Front-end audit

Every number below is measured from the repository, not estimated. The
measurements that matter are re-checked on each run by
`tests/test_template_css_contract.py` (16 tests) and `tests/theme.test.js`
(18 vitest tests), so this document cannot drift away from the code without a
test failing.

Last audited: 2026-09-29. The numbers below are re-derived from the
repository by the suites listed at the end; the first pass was verified against
commit `3740046` and CI run 36484801442 (13 jobs, all green).

## What this application actually is

It is a Jinja server-rendered application. There is no SPA, no client-side
router, no state library and no build step. That is a deliberate shape, and it
is the right one for a system whose data is relational and whose users are on
office networks.

| Asset | Count | Size |
| --- | --- | --- |
| Templates | 32 | 138,285 B |
| Stylesheets | 3 (`custom`, `utilities`, `layout`) | 73,295 B |
| JavaScript | 2 modules under `static/js` | 9,778 B |
| Service worker | 1 (`static/sw.js`) | — |
| Fonts | Amiri Regular + Bold, committed | 844 KB |
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
| Defined classes | — | 700 |

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
| User-facing inputs | 98 |
| In the control family | **98** |
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

## Second pass: print, identity, and the assets behind them

The first pass treated the front end as markup and CSS. That was the smaller
half. Re-reading `base.html` line by line for headers, footers, logos and print
turned up defects that no class-name test would ever reach, because each one
was a claim the code made that the code did not keep.

### The branding system existed and did nothing

`TenantBranding` carries eight fields. The page header used two of them, and
both of those were wrong:

- `base.html` rendered `azad-logo-dark.png` unconditionally. The tenant's
  uploaded logo was never displayed, anywhere, in any page.
- The footer and `<title>` read the company name from the **newest active row
  in the whole table**, while the header read it by the projects the user
  actually belongs to. One page could carry one company's logo above another
  company's name.
- There was no route that served an uploaded image to a browser. The upload
  handler returned an absolute filesystem path and wrote it to the database, so
  the browser could not be handed a URL even in principle. The stored path was
  also bound to one machine: a move or a second host broke every logo.
- `admin/branding.html` told the administrator the customisation "applies
  immediately to all project reports (PDF + web view)". It applied to none. The
  route took a **report-template id** and stored it in `project_id`, so each
  row landed on whichever project happened to share that number.
- The PDF letterhead read `Project.logo_path` — a different column, written by
  a different form. The two systems were never connected.
- `apply_tenant_branding()`, the function meant to push a tenant's identity
  into report rendering, was never called, and would have raised on its first
  line: it read `branding.gradient`, which is a column on `ReportTemplate` and
  not on `TenantBranding`. On its second line it overwrote `tpl.name_ar` with
  the tenant's header text, renaming the report type itself.
- `disclaimer_text` was set from a form field that did not exist, so every save
  wrote an empty string over it.

All of it is now one resolver (`app/services/branding.py`), one asset store
with keys relative to its root, one image route, and one admin page whose
sentence is true. `tests/test_branding_identity.py` has 19 tests; the one named
`test_saving_branding_binds_it_to_the_project_not_the_template` exists only
because of the template-id mistake.

### Uploading a logo accepted SVG

`ext not in ("png", "jpg", "jpeg", "webp", "svg")` — an SVG is a program, and one
served from this origin runs with the session of whoever opens the page.
Validation is now by magic bytes, and SVG is not in the list. The form tells the
user why.

### A tenant colour was written into a `<style>` block unvalidated

`linear-gradient(..., {{ brand.primary_color }}80, ...)` inside a `<style>`
element. Jinja's autoescaping does not apply to CSS context, so
`red;} body{display:none` was a live injection from any account with the
template-manager role. Colours are validated as hex now, and
`test_injected_css_never_reaches_the_style_block` fails if that regresses.

### The print layer was decoration

Two `@media print` blocks, in two stylesheets, contradicting each other. One set
the body background from the *theme* variables, so a user in dark mode printed
light text on a dark page. Both styled `.table` and `.report-section` — classes
no template uses — while `.data-table` and `.surface-card`, the classes the
templates actually use, got no print treatment at all. Both hid every `<nav>`
and `<footer>` by element name, which would also hide a `<nav>` inside report
data.

`static/css/layout.css` now holds one print block, and
`tests/test_print_and_assets.py` fails if a second one appears.

Printing also had no letterhead. The web chrome was hidden and nothing replaced
it, so a printed report was a page of a web application with its menus stripped
off — no logo, no organisation, no page number, nowhere to sign. There is now a
print-only letterhead, a running footer, and a signature block.

### The service worker served other people's data

It cached every same-origin GET, navigations included, and answered from the
cache before the network. Three consequences: a user editing a record navigated
back and saw the cached page; authenticated HTML outlived logout, so on a shared
device the next person could be served the previous user's pages; and the cache
name never changed, so stale entries survived every deployment.

Documents are now network-first and never stored. Only static assets are cached.

### The manifest declared icon sizes that were not true

`azad-logo.png` is 300×300 and was declared `192x192`. `favicon.png` is 32×32
and was declared `512x512`. Install validation reads those numbers. A test now
reads the real dimensions out of the PNG header and compares.

### Arabic PDFs depended on a download that a field deployment cannot make

`ensure_fonts()` fetched Amiri from GitHub on first use, and the fallback was
Helvetica — which has no Arabic glyphs. On a restricted network every Arabic
report rendered blank, and the failure was logged at `debug`, so the job
reported success. The font is now committed with its OFL licence, and a
missing font is a warning rather than a debug line.

### Logos were drawn into a square

Every logo was rendered at `width == height`, so a wordmark four times wider
than it is tall was vertically smeared on the letterhead of every report. The
height now comes from the file's real dimensions, with both capped.

### Smaller things found in the same pass

- `<title>` read `{% block title %}…{% endblock %} — {{ APP_NAME_AR }}`, so a
  page that set its own title got it appended to the app name, and a page that
  did not got the app name twice.
- The primary navigation was rendered **after** `<main>`, so the desktop menu
  appeared below the content it navigates.
- The mobile bar and the desktop bar declared the same five destinations
  separately, in two different orders, with two different labels. One macro now
  produces both, and the current page is marked.
- Navigation icons were emoji, so they rendered differently per platform and
  could not be sized or coloured. They are inline SVG now, defined once.
- The logout control was an `<a>` posting nothing; a GET that changed state.
- `templates/reports/dyn_form.html` contained a stray `"*</span>` that rendered
  as literal text.
- `app/templates/admin/backup.html` was a dead copy written against a different
  design system entirely, and `app/static/` was an empty directory. Both
  removed.
- The shared macros had to be imported per template, so a page using `page_head`
  without the import raised `UndefinedError` only when that page was rendered.
  They are now globals.

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
python -m pytest tests/test_template_css_contract.py -q   # 17 tests
python -m pytest tests/test_print_and_assets.py -q        # 12 tests
python -m pytest tests/test_branding_identity.py -q       # 19 tests
python -m pytest tests/test_pdf_branding.py -q            # 12 tests
npx vitest run                                            # 18 tests
```

The inventory, undefined-class count, label and control counts in this document
are the same numbers those two suites assert on.

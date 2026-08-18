# Dashboard appearance and responsive controls

The dashboard offers light, dark and system colour themes. The preference is
stored in the browser under `qs-theme`; `system` follows the operating system's
colour-scheme setting and updates when that setting changes. A small bootstrap
in the document head applies the saved palette before the application hydrates,
so a dark preference does not flash a light shell on reload. The preference is
presentation-only and never crosses the Gateway or Core service boundary.

## Colour tokens

The palette is a set of CSS variables on `:root`, redefined under
`[data-theme="dark"]`, and exposed as Tailwind utilities through `@theme inline`.
Components name **roles**, never palette steps.

| Utility | Means |
| --- | --- |
| `bg-page`, `bg-surface`, `bg-surface-muted` | The page behind the cards, a card, a recessed area |
| `bg-inverse`, `text-inverse-ink` | A surface that is dark *in the light theme* on purpose — a tooltip, a solid action button |
| `bg-scrim` | The backdrop behind a dialog |
| `text-ink`, `text-ink-secondary`, `text-ink-muted` | Body text, a heading's supporting text, secondary text |
| `text-ink-faint` | **Decoration only** — dividers, a chevron. It is 2.56:1 and must never carry a word or a number |
| `border-line`, `divide-line` | Any hairline |
| `bg-brand`, `hover:bg-brand-hover`, `text-brand-ink` | The brand action colour and what sits on it |
| `bg-{ok,warn,danger,info}-soft`, `text-…-ink`, `border-…-line`, `bg-…` | Status, as four-part sets: a tint, the text on it, its border, and the saturated colour |
| `bg-code`, `text-code-ink` | A code block, dark in *both* themes |
| `text-provider-*` | One hue per connector in the gallery. Decorative, and named so a later sweep does not read Apple Health's red as "danger" |

The type scale is named the same way — `text-nav`, `text-meta`, `text-body`,
`text-emph`, `text-title`, `text-page`, `text-stat` — and its floor is 12px.
`text-nav` is 10px and exists for the two places that size is a platform
convention rather than a choice: bottom-tab labels and a count inside a badge.

`@theme inline` rather than `@theme`: the values are `var(…)` references that
change under the theme selector, and `inline` is what makes a utility resolve
them where it is used rather than freezing the light value at build time.

!!! warning "The `!important` shim this replaced could not have worked"
    Dark mode used to be carried by a block of
    `[data-theme="dark"] .bg-white { … !important }` rules translating Tailwind's
    neutral utilities one class string at a time. Such a layer can only ever
    cover the exact strings somebody thought to list, and the gaps are invisible
    in the source. `.bg-slate-50` was listed and `.bg-slate-50/60` was not — a
    different string — so the chat's whole transcript panel stayed near-white on
    a dark shell. `.text-emerald-800` was listed and `.text-emerald-700` was not.
    `.border-slate-200` was listed and `.ring-slate-200` was not.

    It also could not reach a colour that is not a class at all: a hex inside a
    Chart.js options object or an SVG `stroke` attribute. Every chart in the app
    drew light-theme scaffolding in dark mode for exactly that reason.

    The block is gone. Inline SVG references `var(--color-…)` directly; canvas
    charts read the tokens through `useChartTheme()`, which recomputes when the
    resolved theme changes.

### Keeping it that way

`.agents/scripts/check_design_tokens.py` runs in `task lint:all`. It fails on a
raw palette utility, a pixel font size, or a hex literal in a component — but
only outside its allowlist, which was seeded with every violation that existed
when it was written and shrinks as files are migrated. A rule nobody can satisfy
gets deleted, so it starts from where the code actually is.

Seven entries remain, all of them hex literals that belong where they are: the
map's marker colours, the chart palettes, the manifest's splash colour and the
chart hook's light-theme fallback. `globals.css` is exempt outright — it declares
the tokens, and its comments quote the very class names the rules search for.

### What the browser checks, in both themes

The token checker reads source. It cannot know what a token *resolves to* once the
cascade has run, which is where the interesting failures were: `bg-brand text-white`
satisfies every rule in that script, and in dark mode it painted white on
`#34d399` at a contrast of 1.92 — on every page, because it is the avatar in the
header. Nothing had ever rendered the dark theme in a browser.

`apps/dashboard/e2e/appearance.spec.ts` does. Every destination in `TAB_PATHS`, in
light and dark, at 390px and 1440px — 32 combinations, about a minute — asserting
three things a machine can settle:

- **No accessibility violation axe can name**, WCAG 2.0/2.1 A and AA, which is what
  covers contrast. The allowlist beside it is empty on purpose: the five contrast
  defects the first run found were fixed, not recorded.
- **Nothing overflows horizontally.** Content that scrolls inside its own container
  is fine — a wide table legitimately does — so an element only counts as an
  offender when it exceeds the viewport and no ancestor made itself scrollable.
- **Target sizes**, as described under [Target sizes](#target-sizes-and-which-floor-is-actually-enforced).

The routes come from the `TAB_PATHS` registry rather than a list in the test, so a
new destination is covered the day it is added. Sign-in goes through
`expectAppShell`, which waits for `<main>`: the older `expectSignedIn` looks for the
sidebar's sign-out button, and the sidebar does not exist below `lg` — so it quietly
meant "signed in *and* on a wide screen", and every phone-width test failed looking
like a broken login.

What this does **not** do is judge whether anything looks good. It catches what is
measurably broken and, with the screenshot baselines deliberately left out, nothing
about what merely changed.

### Screens that hold data

A fresh account is empty, so the suite above renders empty states — and an empty
table cannot have a contrast fault in a cell it never draws. `appearance-filled.spec.ts`
is the other half: workout cards, a chart with three series, a day story with lanes,
meals and events, a data-quality list with rows. Same three assertions, same theme and
width matrix.

The data comes from `e2e/fixtures.ts` over intercepted requests, and the page is
otherwise entirely real — real Gateway, real Next build, real session, real layout.
Storybook was considered and rejected for exactly that reason: it renders components in
a second environment, and every visual defect found so far lived in the first one — a
card header that collides only at 390px, a token that resolves wrongly only in dark
mode. A screenshot of an isolated component would have shown neither while looking
authoritative.

Two properties keep the fixtures from rotting into a suite that passes while showing
nothing:

- They are **typed against the app's own response types** (`WorkoutSummary`,
  `DataPointItem`, `ReportEnvelope<DayReport>`), so a shape that drifts is a compile
  error. This caught a day report whose `result` held one day where the page reads
  `result.days` — it had rendered the "Computed …" line and nothing beneath it.
- Units are **derived from the generated metric catalog**, never restated. A first
  version gave `workout_duration` seconds when the registry declares minutes, so a
  45-minute run rendered as "2,700 min", and invented `sleep_score`, which is not a
  registered key (rule 15). Both looked exactly like application bugs. `unitOf()` makes
  the first impossible and the second throw.

Collapsed sections are opened before anything is measured, via the page's own
"Expand all". Without that the day story contributed five headers and no content, so
its substance sat outside the test while the test reported on the screen.

To look at the result rather than trust a green tick:

```bash
QS_SHOTS=1 QS_SHOT_DIR=/tmp/qs-shots bunx playwright test appearance-filled
```

One full-page PNG per route, theme and width. Off by default, because CI does not need
the artefacts and a suite that writes files on every run invites somebody to commit
them. **Two things look broken in a full-page capture and are not**: the sidebar
appears to end mid-page and the phone tab bar appears to float over the content. Both
are `fixed`/`sticky` elements in a stitched image — check them with a viewport-sized
shot instead.

This is how the chart's axis was found reading `2026-08-17T03:00:00Z` at a reader: the
bucket keys that index a series were being used as display labels, which no automated
check can object to and nobody can miss in a picture.

## Phone safe areas

The shell is full-bleed below the `sm` breakpoint, so content reaches the physical
edges of the screen and has to be kept clear of the status bar, the notch, the
rounded corners and the home indicator.

!!! warning "`env(safe-area-inset-*)` is zero without `viewport-fit=cover`"
    The tab bar, the scroll container and the upload banner all carried safe-area
    allowances already, and none of them did anything: the viewport never opted into
    the display cutout, so every one of those expressions evaluated to
    `calc(1rem + 0px)`. A rule that computes to zero looks correct in the source and
    correct in a desktop browser, which is exactly why it survived.

    `viewport.viewportFit = "cover"` in the root layout is what makes the insets
    real. Everything below depends on it.

Insets are applied with `max(…)`, not `calc(… + …)`: on a device with no cutout the
inset is zero and the padding must not collapse to nothing, while on one with a 44px
inset the base padding must not be *added* on top of it. Top and side insets were
missing entirely — in portrait the first heading of every page sat under the status
bar, and in landscape content ran into the camera housing on one edge.

Side and bottom insets are set on `<main>`, the mobile tab bar and its sheet, the
upload banner, the sign-in screen, the legal pages and the OIDC callback. The **top**
inset belongs to the sticky header, because that is now what sits against the status
bar and the notch — `<main>` no longer touches the top of the viewport at all.

`theme-color` is declared per colour scheme rather than as one light value, so the
phone's own chrome no longer paints a near-white strip above a dark shell.

## The shell

The dashboard is an edge-to-edge grid: a sticky sidebar above `md`, a sticky header,
and **the document itself as the scroll container**. The reading measure is set on
the content (`max-w-[1400px]` on `<main>`), not on the chrome, so a page that needs
the full width can opt out of it without fighting the shell.

!!! warning "The centred app window this replaced failed on its own terms"
    The shell used to be a `max-w-[1600px]` card with a shadow, floating on a grey
    mat. Three things were wrong with it at once. `Sidebar` demanded `min-h-screen`
    *inside* a card that itself sat in `lg:p-6`, so the card was always taller than
    the viewport and every desktop carried a permanent strip of dead scroll.
    `sm:min-h-[900px]` forced a 900px card onto 768px-tall laptops and scrolled the
    entire frame — sidebar included — off the screen. And on a large monitor it
    spent hundreds of pixels a side on decoration while capping the width of the
    charts that are the point of the product.

    It also made the scroll topology ambiguous: `<main>` declared `overflow-y-auto`
    while the card had no bounded height. Something scrolled, but not reliably the
    document — which is why iOS Safari never collapsed its address bar here, costing
    around 60px of height permanently on the device with the least to spare, and why
    there was nowhere to put a single `scroll-padding` rule.

`html` carries `scroll-padding-top` and `scroll-padding-bottom` derived from
`--header-h` and `--tabbar-h`, which is what keeps a keyboard-focused element from
coming to rest underneath either fixed bar (WCAG 2.2 SC 2.4.11, *Focus Not
Obscured*). Those two tokens are also what the tab bar and the upload banner measure
themselves against; the three used to agree through separately hand-written
constants, which is to say they agreed until one of them changed.

Every viewport unit is `dvh` rather than `vh`. `100vh` on a mobile browser is the
viewport *without* the address bar, so it overflows by exactly that bar's height for
as long as the bar is showing.

### What the header holds

The header used to carry seven controls in a wrapping row and no page title; on a
phone five survived the breakpoints and wrapped onto two lines before the content of
every page. It now holds the page title, notifications, one primary action on
desktop, and the profile link. The rest moved by how often each is actually needed:

| Control | Where it went | Why |
| --- | --- | --- |
| Notifications | Stays, and is now genuinely persistent | The only place a failed nightly report becomes visible. The header used to render *inside* `<main>` and scrolled away with the page. |
| Add connector | Desktop header; `/connectors` on phone | Rare after setup, but the one "get data in" affordance |
| Refresh | Deleted; survives in the phone "More" sheet | Returning to the tab already re-fetches (`visibilitychange`), each report has its own recompute, and desktop browsers have a reload button |
| Documentation | Sidebar only, and the "More" sheet | The sidebar already had the same link |
| Language, theme | Settings | Set once and then never again |
| Email under the avatar | Settings | `text-[10px]` at 2.56:1 — below the contrast minimum at a size that made it worse |

### Navigation comes from one registry

`components/navigation.ts` is the single source for both surfaces. `PRIMARY_TABS`
and `SECONDARY_TABS` decide the phone tab bar and its "More" sheet; `SIDEBAR_MENU`
and `SIDEBAR_GENERAL` decide the desktop blocks. All four are `filter`s over one
`NAV_ORDER`, so a destination cannot appear on one surface and not the other, and
cannot sit in a different relative order on the two (WCAG 3.2.3). The sidebar's
hand-written `filter(id !== "profile")` was the last hole in that guarantee.

The active tab is no longer distinguished by colour alone (WCAG 1.4.1): it carries a
2px indicator and a heavier label, not just a different hue at identical icon, size
and weight.

### Nothing is truncated in silence

Three lists were showing a slice and looking complete. The workouts list capped
at 100 sessions per request and discarded the `has_more` the server sent; the
Explorer caps each metric at 10,000 points sorted newest-first, so a
whole-history drill-down showed the most recent slice with nothing to say so;
and a session card showed three of however many measures it had.

All three now state it. The card also picks *which* three by what the session is
— volume and sets for lifting, distance and duration for cardio — rather than by
the order the JSON arrived in, which meant two cards side by side could compare
different quantities without either of them saying so.

The workouts list also groups by week above 30 days and by month above 90. A
year of training is roughly two hundred day headings, and a heading per row is
not a grouping.

## Responsive layout

The workout tab has its own `/workouts` route, while the Data Explorer changes its
period segmented control into a native select on narrow screens and stacks custom
start/end dates instead of allowing them to widen the page. Every wide table sits in
its own horizontal scroll container, so a table never widens the page itself.

### Connector setup is a route

`/connectors/new` (optionally `?type=<provider>`) and
`/connectors/<id>/edit` replace a dialog that the dashboard layout carried so
the header's "+" could reach it from any tab. The presentation is unchanged — it
still renders as an overlay over the shell, because both routes are inside that
layout — but the browser's back button now closes it, the address can be linked
from documentation, and an interrupted setup survives a reload.

The dialog's old behaviour was worse than merely stateful: on Android, hardware
back dismissed the *page underneath* the open dialog, and in an installed app
that is the only back affordance there is.

### Target sizes, and which floor is actually enforced

44×44 CSS pixels is the **goal** for interactive targets, and it is worth stating
plainly that the app does not meet it everywhere. The navigation surfaces do. The
dialogs were brought up to it — the close buttons on the connector and import
dialogs, the notification panel's refresh and the upload banner's dismiss were
between 22 and 32 pixels, the smallest of them on the most transient surface.

Roughly forty controls across the Explorer, Workouts, Data Quality, Connectors and
Profile screens still sit between 28 and 42 pixels. That is a visual redesign rather
than a bug fix, so it is recorded rather than quietly done: the browser suite prints
them as `under-44px` annotations on every run, and the count is visible instead of
being implied away by a passing test.

What **is** enforced, as a failing test, is the WCAG 2.5.8 AA floor of 24×24. The
app clears it everywhere, which makes it a real gate: anything that appears below it
is new. Two controls were below it and were fixed when the check was written — the
severity badge's dismiss in the system-warning banner (24×24, a 16px icon with 4px
of padding) and the *Copy* affordance beside the workspace ID on the profile screen
(47×16, a bare text button with no hit area at all).

Text links are exempt from both floors, as WCAG 2.5.8 exempts targets inside a block
of text: the only way to give an underlined link 44 pixels of height is to pad it
until it reads as a button.

The daily story places the current day first and yesterday below it. When a day
has a location lane, the map is loaded on demand and asks Core for that tenant's
whole-day track in the reader's local day window, decimated server-side to fit
(see [GPS visualization](gps-visualization.md)). The browser sends the calendar day
and its UTC offset so the window remains correct around UTC boundaries. Raster map
tiles remain opt-in; the default vector route does not send location data to a tile
provider.

Theme, navigation and responsive controls do not change the meaning or units of
imported metrics. Data remains retrievable through the same tenant-scoped
Gateway APIs documented for the [daily story](daily-story.md), [GPS
visualization](gps-visualization.md), and [workout detail](workout-detail.md).

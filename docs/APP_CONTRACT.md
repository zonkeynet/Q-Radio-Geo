# Q-Globe app ↔ page contract, v1.2 (2026-11-15)

The only interface between the Q-P1NG app (QGlobeActivity, Android) and the Q-Globe page in app mode.
Both sides implement exactly this; any change bumps `v` and is agreed on both sides.

## Transport
- **Page → app:** `WebViewCompat.addWebMessageListener(webView, "qglobeNative", setOf("https://globe.qp1ng.com"), listener)`.
  - The page calls `window.qglobeNative?.postMessage(JSON.stringify(msg))`.
  - It is only present on the allowed origin, so on the website the object is absent and the page behaves as a website.
  - Debug builds may add the local test origin (`http://localhost:<port>`), never release builds.
- **App → page:** `webView.evaluateJavascript("window.qglobeApp && window.qglobeApp.<method>(<json>)", callback)`.
  - The page defines `window.qglobeApp` only in app mode (`?app=1`).
  - Calls that arrive before the page is ready are queued by the app and re-sent after `ready`.
- Every message carries `v: 1`. Unknown types and unknown fields are ignored on both sides (v1.1 only adds optional
  `setTheme` fields, v1.2 the optional `saveNote` message; see below).

## Load URL
`https://globe.qp1ng.com/?app=1&hl=<lang>&mode=<dark|light>`, plus the existing parameters such as the pick mode.
- `hl` is the app language as a BCP 47 primary tag (`it`, `en`; others fall back to `en` on the page).
- `mode` sets the first paint before the full theme arrives, so there is no flash.

## App → page (`window.qglobeApp`)
| Method | Argument | Page does |
|---|---|---|
| `setInsets(o)` | `{v, top, right, bottom, left, ime}` in CSS px | sets `--qg-inset-top/right/bottom/left/ime` on `:root`; layout uses them for safe areas |
| `setTheme(o)` | `{v, mode, surface, surfaceVariant, onSurface, onSurfaceVariant, accent, onAccent, outline, error}` as `#rrggbb`; v1.1 adds `theme`, `palette` and `fonts` (below) | sets the colour roles as CSS custom properties; in the app the page's interface always wears them (v1.1: the palette and the title font on large headings) |
| `setLocale(o)` | `{v, hl}` | switches the UI language without reload, if supported; otherwise the app reloads with the new `hl` |
| `back()` | – | closes the topmost open page layer (search, menu, guide, card, sheet expanded → collapsed, in-page fullscreen); **returns `true` if it consumed Back, `false` otherwise** (evaluateJavascript result string) |
| `command(o)` | `{v, name}`, name ∈ `layers`, `search`, `themes`, `guide`, `rotate`, `lite`, `random` | opens or toggles that page feature (used by the native ⋮ menu); `themes` opens the globe style menu |

## Page → app (`qglobeNative.postMessage`)
| `type` | Fields | App does |
|---|---|---|
| `ready` | `{v, type, layer}` | hides the native loading view (one continuous loading state); flushes queued calls |
| `state` | `{v, type, canGoBack, layer, playing}` | enables or disables its OnBackPressedCallback, so predictive back shows the right preview; `canGoBack` means `back()` would consume |
| `loading` | `{v, type, what, progress?}` | `what` is `layer` / `area` / `catalog`. Before `ready` the app's loading view shows the data step and `progress` (0..1, the share of the first layer's data, when the page knows the size); after `ready` diagnostics only (the page shows its own indicator) |
| `error` | `{v, type, kind, retry}` | `kind` is `network` / `data` / `fatal`. For `fatal` (the page cannot draw) the app shows its native error state with Retry; other errors stay in the page |
| `openExternal` | `{v, type, url, title}` | asks for confirmation in plain words ("Opens outside Q-P1NG: the site will see your connection"), then hands the URL to the system browser; only `https:` URLs, policy permitting |
| `share` | `{v, type, url, title}` | the existing share flow (QGlobeShare) |
| `haptic` | `{v, type, kind}` | `kind` is `tick` / `confirm`; light haptic feedback if the user's settings allow it |
| `saveNote` | `{v, type, kind, title, text, url, source, published, place}` | v1.2: opens the app's own note preview with these fields; the user confirms there. The app answers nothing; an older app ignores it (below) |

## Rules
- The page never assumes the app: every app-mode feature checks `window.qglobeNative` first.
- The app never injects anything outside `window.qglobeApp` calls; no `addJavascriptInterface`.
- Insets and theme are re-sent on every change (rotation, IME, theme switch) and after every page load or reload.
- Back order on the app side:
  1. native fullscreen video;
  2. native video panel;
  3. the page, through `back()` when `canGoBack`;
  4. exit.
- Fullscreen of an embedded player (YouTube or the owner's player) goes through `WebChromeClient.onShowCustomView`; Back leaves fullscreen first.

## saveNote v1.2 (2026-11-15)
Page → app, optional: an older app ignores the type, and messages still carry `v: 1`. Sent only inside the app with the
channel (`window.qglobeNative`), from the "Save to notes" button of a card (news, webcams, a place or the station chosen
in its card, and every layer's item with a title); the website shows nothing new. All fields are plain text, trimmed,
no HTML:

| Field | Value |
|---|---|
| `kind` | `news` / `webcam` / `station` / `place` / the layer id (`sdr`, `aviation`, …) |
| `title` | ≤ 200 characters, one line (never empty: no title, no message) |
| `text` | a short summary, ≤ 2000 characters, lines kept: the news summary, a camera's details, a station's codec, bitrate and genre |
| `url` | the item's own `https:` link (article, owner's page, station homepage), ≤ 2048, no credentials; else `""` |
| `source` | publisher or owner, ≤ 120; else `""` |
| `published` | ISO 8601 (news), else `""` |
| `place` | "City, Country" or "lat, lng", ≤ 120; else `""` |

The page sends a `haptic` tick with it and at most one `saveNote` a second (`js/app-bridge.mjs` `noteMessage`,
`saveNote`; tests in `scripts/test_app_bridge.mjs`).

## setTheme v1.1 (2026-11-15)
v1.1 only adds optional fields to `setTheme`; messages still carry `v: 1`, and a page that does not know them ignores
them (it keeps using the v1 roles). An app that does not send them gets the v1 behaviour.

```
{ v: 1, mode, surface, surfaceVariant, onSurface, onSurfaceVariant, accent, onAccent, outline, error,   // v1
  theme: "paper",                                                                                     // v1.1
  palette: { background, surface, primary, secondary, highlight, error, text, textDim, border },      // #rrggbb
  fonts: { title: { family, url?, axes? }, body: { family, url? }, mono: { family, url? } } }
```
- `theme`: the app's HudTheme id, lowercase (`quantum`, `paper`, `gameboy`…).
- `palette`: the built-in theme's own colours (`highlight` is the app's gold; `mode` stays the top-level field). They
  are the same for everyone using that theme. A custom colour chosen in the app is never sent as is: `primary` and
  `secondary` are then the same coarse accent as `accent`.
- `fonts.title`: the font of the app's titles (the theme's display font, or the font style the user chose), the bold
  file where the family has one. `url` is a same-origin path, `/__qp1ng/fonts/<file>.ttf|otf`; `axes` are variation
  settings for that file (`{"ELSH":50,"CRSV":0,"wght":325}` for Bitcount). No `url` means a system family:
  `sans-serif` or `monospace`.
- `fonts.body` and `fonts.mono`: the app's readable families (system `sans-serif` and `monospace` today), sent for
  completeness. **The page ignores them.**

**The title font goes on large headings only.** The page applies `fonts.title` to its large headings (sheet title,
card title, dialog titles, the guide's title and section headings). Everything else (body text, list rows, subtitles,
chips, buttons, small labels, numbers and distances) stays in the page's own readable system sans and its mono for
numbers, identical for every theme apart from colours.
- Sizes: a pixel font (Press Start 2P, Silkscreen, VT323, Pixelify Sans, Bitcount, the Matrix fonts) at an integer
  multiple of its grid, the largest whose cap height stays within the system-sans heading's, at least 2× the grid
  (VT323's fine 25 px grid: 1×): Press Start 2P and Silkscreen sections 16 px, Silkscreen titles 24, Bitcount and
  Matrix 20, Pixelify 22, VT323 25. Other display fonts 18–22 px from their width, never below 18.
- No synthesized bold or italic, no letter spacing, no forced capitals; balanced line breaks, no hyphenation, a word
  broken only when it is wider than the whole line.
- No layout shift: until the file has loaded, a fallback face (the local system sans, `size-adjust`ed so the sheet title
  has the font's exact width, with the font's ascent, descent and line gap) holds the final box; the page keeps a small
  table of each title font's metrics and character widths for this. A font that fails to load leaves the system font.

**Colours.** Text-bearing panels (sheet, card, dialogs, menus, search results) use the app's exact `surface`, opaque;
the border token and a shadow separate them. Text keeps the app's exact colours where they reach 4.5:1 on that surface
(all 17 built-in themes do); a colour that does not (a custom accent) gets a tone of the same hue (OKLCH lightness, the
least shift) for text only, while fills, icons, indicators and borders keep the exact colour (3:1, WCAG 1.4.11). The
hover layer steps toward the text only while every text colour still reads on it. The page's data colours (the layers'
dots) stay its own.

**Fonts are served by the app.** The viewer answers `GET https://globe.qp1ng.com/__qp1ng/fonts/<file>` itself from the
APK's `res/font` files: a fixed allow-list (exact file name to resource), `font/ttf` or `font/otf`, `Cache-Control:
no-store` (the bytes stay in the app's memory), never a network request. Any other path under `/__qp1ng/` is refused.
The fonts are OFL-1.1 or CC0, served unchanged with their embedded notices (the app's licence notices list them).

**Theme changes.** The viewer runs in its own process and receives the theme in its launch intent; opening Q-Globe
again from the app after a theme change re-sends `setTheme` to the open page.

**Coherent behaviour.** In the app the page's interface always wears the app's theme: its own themes are not offered.
The `themes` command opens the "Globe style" menu ("Stile del globo"), which changes only the globe: automatic (night
lights with a dark app theme, Blue Marble with a light one), night lights, Blue Marble (day, with relief), dotted
continents (in the app's colour). The website keeps its themes and loads no app font.

## Page side (this repository)
- `js/app-bridge.mjs` implements the contract and `js/app-theme.mjs` its v1.1 theme (palette mapping, title font);
  `scripts/test_app_bridge.mjs` checks both.
- `window.qglobeApp` is defined in app mode only; `has-native` is set on `<html>` when `window.qglobeNative` exists.
  Without it (an older app) the page keeps its own theme, guide and rotate buttons and shows external addresses to copy.
- `back()` closes, in this order: the search (results or focused field) → an open menu (layers, themes) → the topmost
  dialog (guide, filters, webcam viewer, address) → the TV channel list → in-page fullscreen → the open card (back to
  the list) → a full-height sheet (back to half height). It answers `false` when none of these is open, so Back from the
  plain globe with its list leaves Q-Globe at once. `state.canGoBack` is exactly "one of these is open".
- `state.playing` is true while the page itself plays something: the website's radio player, a webcam video or an
  embedded live stream (in the app, radio and TV play in the app's player).
- `command`: `layers` opens the layer menu, `search` focuses the search, `themes` opens the globe style menu, `guide` the
  guide, `rotate` toggles rotation, `random` picks something at random in the layer, `lite` reloads with `lite=1`
  switched (same view).
- `setLocale` with a different language reloads the page with the new `hl`; the address keeps the layer, view and card.
- `loading` is sent with `what: layer` or `catalog` when a layer's data starts loading, with `progress` while it
  streams. The page knows the size of its own files from sw-manifest.json (the exact, uncompressed size: the viewer
  passes bodies decompressed and without Content-Length), so `progress` comes for every file of the site, from the
  first layer on.
- `error` is sent with `network` or `data` for a layer that could not load (the page shows Retry), and `fatal` when
  the page cannot draw at all.
- `setTheme` v1.1: `--app-*` variables from the palette (`[data-theme="app"]` in `assets/app.css`; `--primary-text` and
  `--error-text` for those colours as text), the title font as `--qg-font-title`, `--qg-title-size`,
  `--qg-heading-size` and `--qg-title-axes` (`data-title-font`, `data-title-pixel` on `<html>`), applied by
  `assets/native-app.css` to `.sheet-title`, `.dir-card-title`, `.sheet-dialog h2`, `.guide-head h2`, `.native-tv
  header b` and `.guide-section h3` only. The metrics table is `TITLE_FONTS` in `js/app-theme.mjs` (from the font files
  with fontTools). The globe style is kept in `localStorage` (`qradio.globeStyle`).

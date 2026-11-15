# Q-Globe app ↔ page contract, v1 (2026-11-15)

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
- Every message carries `v: 1`. Unknown types are ignored on both sides.

## Load URL
`https://globe.qp1ng.com/?app=1&hl=<lang>&mode=<dark|light>`, plus the existing parameters such as the pick mode.
- `hl` is the app language as a BCP 47 primary tag (`it`, `en`; others fall back to `en` on the page).
- `mode` sets the first paint before the full theme arrives, so there is no flash.

## App → page (`window.qglobeApp`)
| Method | Argument | Page does |
|---|---|---|
| `setInsets(o)` | `{v, top, right, bottom, left, ime}` in CSS px | sets `--qg-inset-top/right/bottom/left/ime` on `:root`; layout uses them for safe areas |
| `setTheme(o)` | `{v, mode, surface, surfaceVariant, onSurface, onSurfaceVariant, accent, onAccent, outline, error}` as `#rrggbb` | sets the colour roles as CSS custom properties; the page's own themes still apply when the user picks one in the page |
| `setLocale(o)` | `{v, hl}` | switches the UI language without reload, if supported; otherwise the app reloads with the new `hl` |
| `back()` | – | closes the topmost open page layer (search, menu, guide, card, sheet expanded → collapsed, in-page fullscreen); **returns `true` if it consumed Back, `false` otherwise** (evaluateJavascript result string) |
| `command(o)` | `{v, name}`, name ∈ `layers`, `search`, `themes`, `guide`, `rotate`, `lite`, `random` | opens or toggles that page feature (used by the native ⋮ menu) |

## Page → app (`qglobeNative.postMessage`)
| `type` | Fields | App does |
|---|---|---|
| `ready` | `{v, type, layer}` | hides the native loading view (one continuous loading state); flushes queued calls |
| `state` | `{v, type, canGoBack, layer, playing}` | enables or disables its OnBackPressedCallback, so predictive back shows the right preview; `canGoBack` means `back()` would consume |
| `loading` | `{v, type, what, progress?}` | `what` is `layer` / `area` / `catalog`; the app may show nothing (the page shows its own indicator); for diagnostics only |
| `error` | `{v, type, kind, retry}` | `kind` is `network` / `data` / `fatal`. For `fatal` (the page cannot draw) the app shows its native error state with Retry; other errors stay in the page |
| `openExternal` | `{v, type, url, title}` | asks for confirmation in plain words ("Opens outside Q-P1NG: the site will see your connection"), then hands the URL to the system browser; only `https:` URLs, policy permitting |
| `share` | `{v, type, url, title}` | the existing share flow (QGlobeShare) |
| `haptic` | `{v, type, kind}` | `kind` is `tick` / `confirm`; light haptic feedback if the user's settings allow it |

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

## Page side (this repository)
- `js/app-bridge.mjs` implements the contract; `scripts/test_app_bridge.mjs` checks it.
- `window.qglobeApp` is defined in app mode only; `has-native` is set on `<html>` when `window.qglobeNative` exists.
  Without it (an older app) the page keeps its own theme, guide and rotate buttons and shows external addresses to copy.
- `back()` closes, in this order: the search (results or focused field) → an open menu (layers, themes) → the topmost
  dialog (guide, filters, webcam viewer, address) → the TV channel list → in-page fullscreen → the open card (back to
  the list) → a full-height sheet (back to half height). It answers `false` when none of these is open, so Back from the
  plain globe with its list leaves Q-Globe at once. `state.canGoBack` is exactly "one of these is open".
- `state.playing` is true while the page itself plays something: the website's radio player, a webcam video or an
  embedded live stream (in the app, radio and TV play in the app's player).
- `command`: `layers` opens the layer menu, `search` focuses the search, `themes` opens the theme menu, `guide` the
  guide, `rotate` toggles rotation, `random` picks something at random in the layer, `lite` reloads with `lite=1`
  switched (same view).
- `setLocale` with a different language reloads the page with the new `hl`; the address keeps the layer, view and card.
- `loading` is sent with `what: layer` or `catalog` when a layer's data starts loading, with `progress` while it streams.
- `error` is sent with `network` or `data` for a layer that could not load (the page shows Retry), and `fatal` when
  the page cannot draw at all.

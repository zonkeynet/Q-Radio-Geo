# Webcam live streams: record shape for the data pipeline (2026-11-15)

The webcam layer shows two kinds of live stream next to HLS, snapshots and web links. The viewer is in
`js/webcams.mjs`; `scripts/test_webcam_streams.mjs` checks it. The pipeline (`scripts/build_webcams.py`) imports the
research records later (`webcam-research/coverage/cams-*.json`: `youtube_channel_live`, `youtube_video`,
`owner_embed`); this is the shape the page accepts.

## Records (in `data/webcams.json` items, or columns of `data/webcams-live.json`)

| Field | YouTube | Owner's player |
|---|---|---|
| `format` | `"youtube"` | `"embed"` |
| `rights_status` | `"official_embed"` (the owner publishes the stream for viewing) | `"official_embed"` |
| `youtube` | `{ "channel": "UC…" }` (a channel's current live, 24 characters) and/or `{ "video": "<11-character id>" }` | – |
| `embed_url` | – | the owner's player, `https:`, on an allowed host (below), no credentials, port or fragment |
| `still_url` | – | optional: an official still image (shown in the app's card) |
| `official_page` | the owner's page about the camera (optional) | the owner's page (opened outside in the app) |
| `id`, `provider`, `name`, `lat`, `lng`, `country`, `region`, coordinates fields, `attribution`, `terms_url`… | as for every webcam | as for every webcam |

Mapping from the research files: `youtube_channel_live` → `youtube.channel = youtube_channel_id`;
`youtube_video` → `youtube.video = youtube_video_id` (keep the channel too when known); `owner_embed` →
`format: "embed"`, `embed_url`; `page_url` → `official_page`. A record that fails validation is left out
(a wrong id, another host, `http:`), like any other invalid webcam row.

## Allowed frame hosts

`EMBED_HOSTS` in `js/webcams.mjs`, mirrored exactly in the `frame-src` of `index.html` (with
`www.youtube-nocookie.com`): `g1/g2/g3.ipcamlive.com`, `ipcamlive.com`, `relay.ozolio.com`, `rtsp.me`,
`iframe.dacast.com`, `api.wetmet.net`, `imageserver.webcamera.pl`, `webcam.elcat.kg`. A new owner host needs both
lists and a review of what its player loads; the test fails if the data names a host that is not allowed.

## What the user sees

- **Website.** The card's main action is "Watch live". The viewer says who will see the connection ("YouTube" or
  the owner's host) and loads nothing until "Load the player": then a frame from `youtube-nocookie.com/embed/<video>`
  or `/embed/live_stream?channel=<UC…>`, or the owner's `embed_url`, with
  `sandbox="allow-scripts allow-same-origin allow-presentation"`, `referrerpolicy="no-referrer"` and
  `allow="autoplay; fullscreen; picture-in-picture"`. Stop, closing the card or hiding the page removes the frame.
- **App (Q-P1NG, with `window.qglobeNative`).** Nothing is ever framed (the app's own policy has `frame-src 'none'`).
  - A YouTube card with a video id shows, only while it is open, the official live thumbnail
    `https://i.ytimg.com/vi/<id>/hqdefault_live.jpg?t=<seconds>` (`hqdefault.jpg` when there is no live image),
    without referrer, with "updated hh:mm" and a refresh button; it refreshes by itself at most once a minute and
    stops when the card closes or the page is hidden. A channel alone, or an image that fails, shows a placeholder
    with the place.
  - The pinned main action "Watch the live" sends `openExternal` with `https://www.youtube.com/watch?v=<id>` (or
    `https://www.youtube.com/channel/<UC…>/live`); the app offers the YouTube app, Tor Browser or a copy. One line
    under it: "The live stream opens outside Q-P1NG."
  - An owner's player: "Open the owner's page" (`official_page`, else the player address) through `openExternal`;
    a preview only from `still_url`.
- The format filter has a "Live streams" chip (both kinds).

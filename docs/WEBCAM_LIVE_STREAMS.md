# Webcam live streams: the owners' YouTube lives and players (2026-11-15)

The webcam layer shows two kinds of live stream next to HLS, snapshots and web links. The viewer is in
`js/webcams.mjs`; `scripts/test_webcam_streams.mjs` checks it. The streams come from one reviewed source in the
repository, `scripts/webcam_live_streams.json`, which `scripts/build_webcams.py --live-streams` imports (source
`owner_live_streams`). The catalogue of the globe coverage is in `docs/WEBCAMS_EXPANSION_2026-11-14.md`.

## Import of 2026-11-15

From the 110 research candidates (confidence high or medium; kinds `youtube_video`, `youtube_channel_live`,
`owner_embed`), **77 are in the catalogue: 64 YouTube lives and 13 owners' players** (11 ipcamlive, 2 Dacast), in 32
countries. The other 33 are in the file's `left_out` list, each with its reason: the owner's terms or wishes (BeachCam
Israel, ElCat, FOX 35, WebCamera.pl), a sanctions check not completed (Najaf), or the checks of that day (not live,
daily ids, another camera on the channel, audio only, a player that does not start outside the owner's site, a
suspended player account). Snapshot pages (`page`) were out of scope.

Every record was checked on 2026-11-15 from a PC, directly (no Tor), at most one request every 0.6 s with a browser
User-Agent:

- **YouTube.** oEmbed (`https://www.youtube.com/oembed?url=…&format=json`) answered 200, so the owner allows embedding;
  the watch page said live now and playable in an embed. For each channel, `/channel/<UC…>/live` and the channel's
  Live tab: when the channel carries only this live and `/live` plays it (7 records), the record has the channel
  (which survives a restart) and the video (the app's thumbnail); a channel with several lives keeps the video only.
  Five ids had changed since the research (same title on the owner's channel): the record has the new id and the old
  one in `previous_videos`.
- **Owners' players.** The host is in `EMBED_HOSTS`. The players themselves were not fetched by script where
  robots.txt keeps agents out (ipcamlive disallows Anthropic's agents; Ozolio and Dacast disallow all agents). The
  Dacast, Ozolio and rtsp.me players were opened once in Chrome on a phone, framed as the globe frames them: Dacast
  plays; Ozolio never starts outside the owner's site and rtsp.me shows "Streaming access is temporarily restricted",
  so those are left out. The 11 ipcamlive players were not opened.

## The source file

`scripts/webcam_live_streams.json` (schema 1, `source: owner_live_streams`) holds only what the pipeline needs, plus
evidence: `provider_id`, `name`, `country`, `region`, `lat`/`lng`, `format`, `youtube` (`channel`/`video`) or
`embed_url`, `official_page` (the owner's page), `source_page` when the owner's site is elsewhere, `owner`, the
placement (`coordinate_role`, `coordinate_source`, `coordinate_source_licence`, `coordinate_feature`,
`coordinate_uncertainty_m`), a short `reason` and the dated `check`. Placement roles: `named_feature` and
`place_centre` as for every placed camera (OpenStreetMap ODbL, Wikidata CC0, Wikipedia, Natural Earth);
`associated_feature` when the owner's stated position is the subject shown (two volcanoes); `approximate` for an
owner's map centre (Sydney). No credentials, private or dynamic-DNS hosts or device paths: the loader applies the
pipeline's privacy filter to every link, and the whole-record sweep runs as for every source.

The builder admits a record only while its `check.result` is `ok`. It writes `format: youtube` or `embed`,
`rights_status: official_embed`, `official_page`, `attribution` (the owner; "(YouTube)" for YouTube) and `terms_url`
(YouTube's terms, or the owner's page). The full record (SQLite, `data/webcams.json`) keeps the check; the viewable
file the globe loads first (`data/webcams-live.json`) has every live stream, so the "Live streams" chip lists them
without the full catalogue.

## Re-verify

```bash
python scripts/check_live_streams.py                 # every record; --only <provider_id> … for some, --dry-run to look
```

It rewrites each record's `check` with the date and `ok` or `fail` and a reason. A channel that now plays another video
moves the record to the new id (the old one goes to `previous_videos`). A record that fails stays in the file and stays
out of the catalogue: find the camera's new id on the owner's channel, or move it to `left_out` with the reason. Then
rebuild (the command in `docs/WEBCAMS_EXPANSION_2026-11-14.md`, with `--live-streams scripts/webcam_live_streams.json`),
run `node scripts/build_sw.mjs` and the tests. Lives of multi-stream channels (most of them) change id when the stream
restarts; a monthly check keeps them current.

## Duplicates

A live stream and another record of the same camera become one (`drop_live_duplicates`, `reports/webcams/duplicates.json`):

- **Same stream:** the other record links the same YouTube video (or a `previous_videos` id), channel or owner player,
  within the live record's stated uncertainty (300 m to 5 km).
- **Same owner, same place:** otherwise, the nearest record within 300 m whose links are on the owner's own site
  (video platforms and frame hosts do not count).

The live stream stays and keeps the other record's page as a reference, unless the other record is an admitted HLS or
snapshot feed: then the feed stays. On 2026-11-15, 13 community records (OSM, Wikidata) merged into live streams.

## Records (in `data/webcams.json` items, or columns of `data/webcams-live.json`)

| Field | YouTube | Owner's player |
|---|---|---|
| `format` | `"youtube"` | `"embed"` |
| `rights_status` | `"official_embed"` (the owner publishes the stream for viewing) | `"official_embed"` |
| `youtube` | `{ "channel": "UC…" }` (a channel's current live, 24 characters) and/or `{ "video": "<11-character id>" }` | – |
| `embed_url` | – | the owner's player, `https:`, on an allowed host (below), no credentials, port or fragment |
| `still_url` | – | optional: an official still image (shown in the app's card) |
| `official_page` | the owner's page about the camera | the owner's page (opened outside in the app) |
| `attribution`, `terms_url` | the owner (YouTube), YouTube's terms | the owner, the owner's page |
| `id`, `provider`, `name`, `lat`, `lng`, `country`, `region`, coordinates fields… | as for every webcam | as for every webcam |

## Allowed frame hosts

`EMBED_HOSTS` in `js/webcams.mjs`, mirrored exactly in the `frame-src` of `index.html` (with
`www.youtube-nocookie.com`) and in `scripts/build_webcams.py`: `g1/g2/g3.ipcamlive.com`, `ipcamlive.com`,
`relay.ozolio.com`, `rtsp.me`, `iframe.dacast.com`, `api.wetmet.net`, `imageserver.webcamera.pl`, `webcam.elcat.kg`. A
new owner host needs the three lists and a review of what its player loads (https only, no trackers beyond the player);
the tests fail if they differ or if the data names a host that is not allowed. No host was added on 2026-11-15. The
data now uses only ipcamlive and Dacast: `imageserver.webcamera.pl` serves a thumbnail-and-link widget that loads
Google Analytics, and `relay.ozolio.com`, `rtsp.me`, `api.wetmet.net` and `webcam.elcat.kg` have no record.

## What the user sees

- **Website.** The card's main action is "Watch live". The viewer says who will see the connection ("YouTube", with
  this site's address, or the owner's host) and loads nothing until "Load the player": then a frame with
  `sandbox="allow-scripts allow-same-origin allow-presentation"` and `allow="autoplay; fullscreen; picture-in-picture"`:
  - from `youtube-nocookie.com/embed/live_stream?channel=<UC…>` when the record has a channel, else `/embed/<video>`,
    with `referrerpolicy="strict-origin-when-cross-origin"`: YouTube's player refuses to start without the embedding
    site (error 153, "player configuration"), so it gets this site's origin, never the page address;
  - or the owner's `embed_url`, with `referrerpolicy="no-referrer"`.

  Stop, closing the card or hiding the page removes the frame.
- **App (Q-P1NG, with `window.qglobeNative`).** Nothing is ever framed (the app's own policy has `frame-src 'none'`).
  - A YouTube card with a video id shows, only while it is open, the official live thumbnail
    `https://i.ytimg.com/vi/<id>/hqdefault_live.jpg?t=<seconds>` (`hqdefault.jpg` when there is no live image),
    without referrer, with "updated hh:mm" and a refresh button; it refreshes by itself at most once a minute and
    stops when the card closes or the page is hidden. A channel alone, or an image that fails, shows a placeholder
    with the place.
  - The pinned main action "Watch the live" sends `openExternal` with `https://www.youtube.com/channel/<UC…>/live` when
    the record has a channel, else `https://www.youtube.com/watch?v=<id>`; the app offers the YouTube app, Tor Browser
    or a copy. One line under it: "The live stream opens outside Q-P1NG."
  - An owner's player: "Open the owner's page" (`official_page`, else the player address) through `openExternal`;
    a preview only from `still_url`.
- The format filter has a "Live streams" chip (both kinds).

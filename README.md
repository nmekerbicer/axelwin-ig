# axelwin-ig

Publishing and reporting automation for **@axelwin_agency** on Instagram.

The repo does three jobs:

1. **Hosts the assets.** Meta's publishing API fetches images and videos from a public URL and refuses file uploads, so the finished JPEGs and MP4s live in `assets/` and GitHub serves them.
2. **Publishes on schedule.** A GitHub Action runs every 10 minutes, looks in `queue.json` for posts whose slot has arrived, and publishes them through the Instagram Graph API. Nothing has to be open on anyone's machine.
3. **Reads performance back.** A weekly Action pulls reach, views, saves, shares and profile visits into `data/insights.json` and `data/insights.md`, so each batch gets planned on evidence.

## Layout

```
assets/            JPEG slides and MP4 reels, publicly served
queue.json         the schedule. One entry per post
scripts/publish.py     publishes anything due
scripts/insights.py    weekly performance pull
scripts/token_check.py warns before the 60 day token expires
scripts/prep_assets.py converts rendered PNGs to API-ready JPEGs
data/              insights, token status and the publish log
```

## Configuration

Repository **secrets** (Settings, Secrets and variables, Actions):

| Name | Value |
|---|---|
| `IG_TOKEN` | long-lived access token, 60 day life |
| `IG_USER_ID` | Instagram Business Account ID |

Repository **variables**, same screen, Variables tab:

| Name | Value |
|---|---|
| `ASSET_BASE_URL` | public base URL of `assets/`, for example `https://<user>.github.io/axelwin-ig/assets` |
| `GRAPH_VERSION` | optional, defaults to `v23.0` |

## Adding a post

Put the files in `assets/`, then add an entry to `queue.json`:

```json
{
  "id": "2026-08-19-german-checkout",
  "status": "pending",
  "publish_at": "2026-08-19T07:00:00Z",
  "type": "CAROUSEL",
  "pillar": "P1 Germany Decoded",
  "files": ["aug19_01.jpg", "aug19_02.jpg", "aug19_03.jpg"],
  "caption": "First line carries the search phrase.\n\nBody.\n\n#GermanMarketEntry #DTC"
}
```

- `publish_at` is **UTC**. Hamburg summer time is UTC+2, so 09:00 in Hamburg is `07:00:00Z`. Winter time is UTC+1.
- `status` must be `pending` for a post to go out. `template` and `example` entries are ignored, `published`, `error` and `missed` are results.
- `files` are in true reading order. The Meta Business Suite carousel scramble does not exist here, the API keeps the order it is given.
- Images must be **JPEG**. Run `python scripts/prep_assets.py <folder> --prefix aug19` to convert rendered PNGs and get the file list to paste in.
- `type` is `IMAGE`, `CAROUSEL` (up to 10 slides) or `REEL`.

## Testing before anything goes live

Actions tab, "Publish due Instagram posts", **Run workflow**, tick **dry run**. It resolves every asset URL, confirms Instagram will be able to fetch each one, and publishes nothing.

## Guardrails built in

- A post more than 4 hours past its slot is marked `missed` instead of publishing late.
- At most 3 posts publish per run.
- Every asset URL is checked before a container is created, so a typo fails loudly with a clear message and no half-built carousel.
- Video containers are polled until Instagram finishes transcoding.
- The weekly token check fails the workflow when fewer than 10 days remain, which sends a GitHub email. That email is the signal to generate a new token.

## Limits worth knowing

- 100 API-published posts per 24 hours, and carousels count as one.
- 10 slides per carousel.
- JPEG only for images.
- The API has no native scheduling. `publish_at` plus the 10 minute cron is the scheduler.

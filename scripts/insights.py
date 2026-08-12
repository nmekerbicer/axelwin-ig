#!/usr/bin/env python3
"""Pull account and per-post insights for @axelwin_agency into data/.

Writes data/insights.json (machine readable, one entry per post) and
data/insights.md (a table to read at a glance). Runs weekly in Actions.
The repo is public, so the results can be read back without any credential.

Environment: IG_TOKEN, IG_USER_ID, GRAPH_VERSION (optional).
"""

import json
import os
import sys
import datetime as dt
import urllib.parse
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

TOKEN = os.environ.get("IG_TOKEN", "").strip()
IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
GRAPH = os.environ.get("GRAPH_VERSION", "v23.0").strip()
BASE = f"https://graph.facebook.com/{GRAPH}"

# Requested per media type. Meta retires metric names periodically, so each
# metric is requested individually and a rejected one is recorded as null
# instead of failing the whole run.
METRICS = {
    "IMAGE": ["reach", "views", "likes", "comments", "shares", "saved", "total_interactions", "profile_visits", "follows"],
    "CAROUSEL_ALBUM": ["reach", "views", "likes", "comments", "shares", "saved", "total_interactions", "profile_visits", "follows"],
    "VIDEO": ["reach", "views", "likes", "comments", "shares", "saved", "total_interactions", "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"],
}
ACCOUNT_METRICS = ["reach", "views", "profile_views", "website_clicks", "accounts_engaged", "total_interactions"]


def api(path, params=None):
    params = dict(params or {})
    params["access_token"] = TOKEN
    url = f"{BASE}/{path.lstrip('/')}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body)["error"].get("message", body[:300])
        except Exception:
            msg = body[:300]
        raise RuntimeError(msg) from None


def media_insights(media_id, media_type):
    out = {}
    for metric in METRICS.get(media_type, METRICS["IMAGE"]):
        try:
            data = api(f"{media_id}/insights", {"metric": metric})["data"]
            out[metric] = data[0]["values"][0]["value"] if data else None
        except Exception as e:
            out[metric] = None
            out.setdefault("_unavailable", []).append(f"{metric}: {e}")
    return out


def account_insights():
    out = {}
    since = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).timestamp())
    until = int(dt.datetime.now(dt.timezone.utc).timestamp())
    for metric in ACCOUNT_METRICS:
        try:
            data = api(f"{IG_USER_ID}/insights", {
                "metric": metric, "period": "day",
                "metric_type": "total_value", "since": since, "until": until,
            })["data"]
            out[metric] = data[0].get("total_value", {}).get("value") if data else None
        except Exception:
            out[metric] = None
    try:
        prof = api(IG_USER_ID, {"fields": "followers_count,media_count,username"})
        out.update(prof)
    except Exception:
        pass
    return out


def main():
    if not (TOKEN and IG_USER_ID):
        print("missing IG_TOKEN or IG_USER_ID")
        return 1

    media = api(f"{IG_USER_ID}/media", {
        "fields": "id,caption,media_type,media_product_type,permalink,timestamp",
        "limit": 50,
    }).get("data", [])

    rows = []
    for m in media:
        stats = media_insights(m["id"], m.get("media_type", "IMAGE"))
        caption = (m.get("caption") or "").split("\n")[0][:70]
        rows.append({
            "id": m["id"],
            "posted": m.get("timestamp"),
            "type": m.get("media_product_type") or m.get("media_type"),
            "permalink": m.get("permalink"),
            "hook": caption,
            **{k: v for k, v in stats.items() if not k.startswith("_")},
        })

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "account": account_insights(),
        "posts": rows,
    }
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "insights.json"), "w") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    acc = payload["account"]
    lines = [
        f"# @{acc.get('username', 'axelwin_agency')} insights",
        "",
        f"Generated {payload['generated_at']} UTC. Account totals cover the last 30 days.",
        "",
        f"- Followers: {acc.get('followers_count')}",
        f"- Posts: {acc.get('media_count')}",
        f"- Reach (30d): {acc.get('reach')}",
        f"- Profile views (30d): {acc.get('profile_views')}",
        f"- Website clicks (30d): {acc.get('website_clicks')}",
        f"- Accounts engaged (30d): {acc.get('accounts_engaged')}",
        "",
        "| Posted | Type | Hook | Reach | Views | Saves | Shares | Likes | Comments |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        posted = (r["posted"] or "")[:10]
        hook = (r["hook"] or "").replace("|", "/")
        lines.append(
            f"| {posted} | {r['type']} | [{hook}]({r['permalink']}) | {r.get('reach')} | "
            f"{r.get('views')} | {r.get('saved')} | {r.get('shares')} | {r.get('likes')} | {r.get('comments')} |"
        )
    with open(os.path.join(DATA, "insights.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"wrote {len(rows)} posts to data/insights.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

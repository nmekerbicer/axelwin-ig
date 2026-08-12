#!/usr/bin/env python3
"""Publish due Instagram posts from queue.json through the Instagram Graph API.

Runs on a schedule in GitHub Actions. Reads queue.json, finds entries whose
publish_at has passed and whose status is "pending", publishes them, then
writes the queue back with status, media id and permalink filled in.

Environment:
  IG_TOKEN        long-lived Instagram/Facebook access token   (required, secret)
  IG_USER_ID      Instagram Business Account ID                (required)
  ASSET_BASE_URL  public base URL for the assets folder        (required)
  GRAPH_VERSION   Graph API version, defaults to v23.0         (optional)
  DRY_RUN         "1" to resolve and validate without posting  (optional)
"""

import json
import os
import sys
import time
import datetime as dt
import urllib.parse
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_PATH = os.path.join(ROOT, "queue.json")
LOG_PATH = os.path.join(ROOT, "data", "publish_log.json")

TOKEN = os.environ.get("IG_TOKEN", "").strip()
IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
ASSET_BASE = os.environ.get("ASSET_BASE_URL", "").strip().rstrip("/")
GRAPH = os.environ.get("GRAPH_VERSION", "v23.0").strip()
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"
BASE = f"https://graph.facebook.com/{GRAPH}"

# Publish at most this many posts in a single run. Guards against a bad
# publish_at date dumping the whole queue onto the account at once.
MAX_PER_RUN = 3
# How late a post may be and still go out. Beyond this it is marked missed,
# so a workflow outage does not publish a Tuesday post on Friday.
MAX_LATENESS_MIN = 240


def log(msg):
    print(f"[{dt.datetime.now(dt.timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def api(path, params=None, post=False, retries=3):
    params = dict(params or {})
    params["access_token"] = TOKEN
    url = f"{BASE}/{path.lstrip('/')}"
    for attempt in range(1, retries + 1):
        try:
            if post:
                data = urllib.parse.urlencode(params).encode()
                req = urllib.request.Request(url, data=data, method="POST")
            else:
                req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params))
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            try:
                err = json.loads(body)["error"]
                detail = f"{err.get('type')} {err.get('code')}: {err.get('message')}"
                transient = err.get("code") in (1, 2, 4, 17, 32, 613)
            except Exception:
                detail = body[:400]
                transient = e.code >= 500
            if attempt < retries and transient:
                wait = 5 * attempt
                log(f"  transient error, retry in {wait}s: {detail}")
                time.sleep(wait)
                continue
            raise RuntimeError(detail) from None
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(5 * attempt)
                continue
            raise RuntimeError(f"network error: {e}") from None


def asset_url(filename):
    if filename.startswith("http://") or filename.startswith("https://"):
        return filename
    return f"{ASSET_BASE}/{urllib.parse.quote(filename)}"


def check_reachable(url):
    """Meta fetches the asset itself, so a 404 here means a failed publish."""
    req = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if not (ctype.startswith("image/") or ctype.startswith("video/")):
                raise RuntimeError(f"unexpected content-type {ctype} at {url}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"asset not reachable ({e.code}) at {url}") from None


def wait_for_container(container_id, minutes=5):
    """Video containers transcode asynchronously. Images finish immediately."""
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        info = api(container_id, {"fields": "status_code,status"})
        code = info.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {code}: {info.get('status', '')}")
        log(f"  container {container_id} {code}, waiting")
        time.sleep(20)
    raise RuntimeError("container did not finish within 5 minutes")


def build_container(post):
    ptype = post["type"].upper()
    caption = post.get("caption", "")
    files = post.get("files", [])
    if not files:
        raise RuntimeError("post has no files")

    if ptype == "IMAGE":
        url = asset_url(files[0])
        check_reachable(url)
        params = {"image_url": url, "caption": caption}
        if post.get("location_id"):
            params["location_id"] = post["location_id"]
        return api(f"{IG_USER_ID}/media", params, post=True)["id"]

    if ptype in ("REEL", "REELS"):
        url = asset_url(files[0])
        check_reachable(url)
        params = {"media_type": "REELS", "video_url": url, "caption": caption}
        if post.get("cover"):
            params["cover_url"] = asset_url(post["cover"])
        if post.get("share_to_feed") is not False:
            params["share_to_feed"] = "true"
        if post.get("location_id"):
            params["location_id"] = post["location_id"]
        cid = api(f"{IG_USER_ID}/media", params, post=True)["id"]
        wait_for_container(cid)
        return cid

    if ptype == "CAROUSEL":
        if len(files) > 10:
            raise RuntimeError(f"carousel has {len(files)} slides, limit is 10")
        children = []
        for f in files:
            url = asset_url(f)
            check_reachable(url)
            is_video = f.lower().endswith((".mp4", ".mov"))
            params = {"is_carousel_item": "true"}
            if is_video:
                params.update({"media_type": "VIDEO", "video_url": url})
            else:
                params["image_url"] = url
            cid = api(f"{IG_USER_ID}/media", params, post=True)["id"]
            if is_video:
                wait_for_container(cid)
            children.append(cid)
            log(f"  slide {len(children)}/{len(files)} -> {cid}")
        params = {
            "media_type": "CAROUSEL",
            "children": ",".join(children),
            "caption": caption,
        }
        if post.get("location_id"):
            params["location_id"] = post["location_id"]
        return api(f"{IG_USER_ID}/media", params, post=True)["id"]

    raise RuntimeError(f"unknown post type {ptype!r}")


def publish(post):
    log(f"publishing {post['id']} ({post['type']}, {len(post.get('files', []))} file(s))")
    if DRY_RUN:
        for f in post.get("files", []):
            check_reachable(asset_url(f))
        log("  dry run, assets reachable, nothing published")
        return {"status": "pending", "dry_run_ok": True}
    container = build_container(post)
    result = api(f"{IG_USER_ID}/media_publish", {"creation_id": container}, post=True)
    media_id = result["id"]
    permalink = ""
    try:
        permalink = api(media_id, {"fields": "permalink"}).get("permalink", "")
    except Exception:
        pass
    log(f"  published as {media_id} {permalink}")
    return {
        "status": "published",
        "ig_media_id": media_id,
        "permalink": permalink,
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "error": "",
    }


def parse_time(value):
    """publish_at is ISO 8601. A bare timestamp is read as UTC."""
    t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t


def main():
    missing = [n for n, v in (("IG_TOKEN", TOKEN), ("IG_USER_ID", IG_USER_ID),
                              ("ASSET_BASE_URL", ASSET_BASE)) if not v]
    if missing:
        log(f"missing configuration: {', '.join(missing)}")
        return 1

    with open(QUEUE_PATH) as fh:
        queue = json.load(fh)
    posts = queue["posts"] if isinstance(queue, dict) else queue

    now = dt.datetime.now(dt.timezone.utc)
    due = []
    for p in posts:
        # A dry run validates everything in the file, including examples and
        # posts still scheduled for the future, and never writes anything back.
        if DRY_RUN:
            if p.get("status") not in ("pending", "example"):
                continue
            due.append(p)
            continue
        if p.get("status", "pending") != "pending":
            continue
        when = parse_time(p["publish_at"])
        if when > now:
            continue
        late_min = (now - when).total_seconds() / 60
        if late_min > MAX_LATENESS_MIN:
            p["status"] = "missed"
            p["error"] = f"skipped, {int(late_min)} minutes late"
            log(f"{p['id']} skipped, {int(late_min)} minutes past its slot")
            continue
        due.append(p)

    if not due:
        log("nothing due")
    changed = bool([p for p in posts if p.get("status") == "missed" and p.get("error")])

    batch = sorted(due, key=lambda x: x["publish_at"]) if DRY_RUN \
        else sorted(due, key=lambda x: x["publish_at"])[:MAX_PER_RUN]
    failed = []
    for p in batch:
        try:
            result = publish(p)
            if not DRY_RUN:
                p.update(result)
        except Exception as e:
            if not DRY_RUN:
                p["status"] = "error"
                p["error"] = str(e)
            failed.append(p.get("id"))
            log(f"  FAILED: {e}")
        changed = True

    if DRY_RUN:
        log(f"dry run complete, {len(batch)} post(s) checked, {len(failed)} problem(s)")
        return 1 if failed else 0

    if changed:
        with open(QUEUE_PATH, "w") as fh:
            json.dump(queue, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        entries = []
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH) as fh:
                entries = json.load(fh)
        entries.append({
            "run_at": now.isoformat(timespec="seconds"),
            "results": [{k: p.get(k) for k in ("id", "status", "ig_media_id", "permalink", "error")}
                        for p in due],
        })
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "w") as fh:
            json.dump(entries[-200:], fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    failures = [p for p in due if p.get("status") == "error"]
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Check how long the access token has left and write data/token_status.json.

Long-lived tokens last 60 days. This runs weekly alongside insights and exits
non-zero when fewer than 10 days remain, which turns into a failed-workflow
email from GitHub. That email is the reminder to refresh the token.
"""

import json
import os
import sys
import datetime as dt
import urllib.parse
import urllib.request

TOKEN = os.environ.get("IG_TOKEN", "").strip()
GRAPH = os.environ.get("GRAPH_VERSION", "v23.0").strip()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WARN_DAYS = 10


def main():
    if not TOKEN:
        print("missing IG_TOKEN")
        return 1
    url = f"https://graph.facebook.com/{GRAPH}/debug_token?" + urllib.parse.urlencode(
        {"input_token": TOKEN, "access_token": TOKEN})
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read().decode()).get("data", {})

    expires_at = data.get("expires_at") or 0
    now = dt.datetime.now(dt.timezone.utc)
    if expires_at == 0:
        status = {"expires": "never", "days_left": None}
        days_left = 999
    else:
        expiry = dt.datetime.fromtimestamp(expires_at, dt.timezone.utc)
        days_left = (expiry - now).days
        status = {"expires": expiry.isoformat(timespec="seconds"), "days_left": days_left}

    status.update({
        "checked_at": now.isoformat(timespec="seconds"),
        "valid": data.get("is_valid"),
        "scopes": data.get("scopes", []),
        "app_id": data.get("app_id"),
    })
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "token_status.json"), "w") as fh:
        json.dump(status, fh, indent=2)
        fh.write("\n")

    print(json.dumps(status, indent=2))
    if not data.get("is_valid"):
        print("TOKEN INVALID. Publishing is stopped until it is replaced.")
        return 1
    if days_left <= WARN_DAYS:
        print(f"TOKEN EXPIRES IN {days_left} DAYS. Generate a new long-lived token "
              f"and update the IG_TOKEN secret.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Fetch the tickets from the saved API connection and save them as the active dataset. For a scheduler (cron, Windows Task
Scheduler, a GitHub Action): the app itself cannot run jobs in the background.

    python refresh.py

Uses the URL, header and field mapping saved under Data > Connect an API, and the token in RIDEOPS_API_TOKEN. Uses the same
database as the app (RIDEOPS_STORE or DATABASE_URL). Nothing is saved when the data is unchanged since the last refresh or
does not read as a ticket export; the app shows the last result under the API form. Exit code 0 = fine (saved or unchanged),
1 = failed.
"""
import hashlib
import io
import sys

import connect
import engine as E
import os
import store


def main(token: str | None = None) -> int:
    api = store.kv_get("api", {}) or {}
    last = {"at": store.now().isoformat(timespec="minutes"), "ok": False, "message": ""}
    try:
        if not api.get("url"):
            raise ValueError("no API connection is saved yet (Data > Connect an API in the app)")
        tok = token if token is not None else os.environ.get("RIDEOPS_API_TOKEN", "")
        raw = connect.fetch_frame(api["url"], api.get("header", "Authorization"), tok)
        frame = connect.apply_mapping(raw, api.get("mapping", {}))
        gaps = connect.missing(frame, E.REQUIRED)
        if gaps:
            raise ValueError("fields missing after mapping: " + ", ".join(gaps) + " (map them in the app)")
        content = connect.to_bytes(frame)
        E.load(io.BytesIO(content))                          # raises if it does not read as a ticket export
        sha = hashlib.sha256(content).hexdigest()
        prev = store.kv_get("api_last", {}) or {}
        if prev.get("sha") == sha:
            last.update(ok=True, sha=sha, message=f"no change ({len(frame):,} tickets)")
        else:
            ds = store.save_dataset(f"{api['url'].split('/')[2]} scheduled", content, "api")
            last.update(ok=True, sha=sha, message=f"saved {len(frame):,} tickets as export {ds}")
    except (OSError, ValueError, KeyError) as err:
        last["message"] = f"failed: {err}"
    store.kv_set("api_last", last)
    print(last["message"])
    return 0 if last["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

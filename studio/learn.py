"""Learns what works from a creator channel's public Shorts (metadata only, no API key)."""
import difflib
import json
import re
import statistics as st
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

STOP = set("the a an this that when how why what who i he she they we you it my his her their top best new first last just so and but if watch can did does is are was".split())


def med(v):
    return st.median(v) if v else 0


def fetch_channel_shorts(url: str, limit: int = 60, cache_file: Path | None = None) -> list:
    """Fetch public Shorts entries for a YouTube channel."""
    if cache_file and cache_file.exists() and time.time() - cache_file.stat().st_mtime < 86400:
        try:
            return json.loads(cache_file.read_text(encoding="utf-8")).get("entries", [])
        except Exception:
            pass

    u = url if url.startswith("http") else "https://www.youtube.com/" + url.lstrip("/")
    if not u.rstrip("/").endswith("/shorts"):
        u = u.rstrip("/") + "/shorts"

    r = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "-J", "--flat-playlist", "--playlist-end", str(limit), "--skip-download", u],
        capture_output=True, text=True, encoding="utf-8", timeout=300
    )
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(f"Could not fetch channel: {r.stderr[-300:]}")

    data = json.loads(r.stdout)
    if cache_file:
        try:
            cache_file.write_text(r.stdout, encoding="utf-8")
        except Exception:
            pass
    return data.get("entries", [])


def analyze_shorts(entries: list, channel_name: str = "") -> dict:
    """Extract view patterns and actionable rules from a channel's Shorts."""
    rows = []
    for e in entries:
        if e.get("view_count") is None:
            continue
        t = e.get("title") or ""
        w = re.findall(r"[A-Za-z0-9']+", t)
        first = w[0] if w else ""
        dur = e.get("duration")
        rows.append({
            "title": t,
            "views": e["view_count"],
            "length": None if not dur else ("under 20s" if dur < 20 else ("20-35s" if dur <= 35 else "over 35s")),
            "name_first": bool(first[:1].isupper() and first.lower() not in STOP),
            "has_number": bool(re.search(r"\d", t)),
            "is_question": "?" in t
        })

    if not rows:
        return {"channel": channel_name, "shorts_count": 0, "rules": []}

    base = med([r["views"] for r in rows])
    rules = []

    # Check lengths
    for l_bucket in ("under 20s", "20-35s", "over 35s"):
        group = [r["views"] for r in rows if r["length"] == l_bucket]
        if len(group) >= 3:
            ratio = med(group) / max(1, base)
            if ratio >= 1.3 or ratio <= 0.7:
                rules.append(f"Length {l_bucket} gets {ratio:.1f}x the median views ({len(group)} Shorts)")

    # Title structures
    for key, label in [("name_first", "Hooks starting with a name/entity"), ("has_number", "Titles with numbers"), ("is_question", "Titles asking questions")]:
        a = [r["views"] for r in rows if r[key]]
        b = [r["views"] for r in rows if not r[key]]
        if len(a) >= 3 and len(b) >= 3:
            ratio = med(a) / max(med(b), 1)
            if ratio >= 1.3 or ratio <= 0.7:
                rules.append(f"{label} get {ratio:.1f}x the views of those without")

    return {
        "channel": channel_name,
        "shorts_count": len(rows),
        "median_views": int(base),
        "rules": rules,
        "top_titles": [r["title"] for r in sorted(rows, key=lambda x: -x["views"])[:3]]
    }

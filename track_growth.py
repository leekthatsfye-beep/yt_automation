"""
track_growth.py

Logs a daily snapshot of your YouTube channel stats to growth_log.json.
Run once a day (or set up a cron job) to track growth from now to June 25th.

Usage:
    python track_growth.py          # log today's snapshot
    python track_growth.py --report # print full growth report
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from youtube_auth import get_youtube_service_with_fallback

ROOT     = Path(__file__).resolve().parent
LOG_FILE = ROOT / "growth_log.json"

START_DATE  = "2026-03-30"   # today — baseline
GOAL_DATE   = "2026-06-25"   # birthday milestone (tracking continues forever after)


def load_log():
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text())
    return []


def save_log(log):
    LOG_FILE.write_text(json.dumps(log, indent=2))


def fetch_stats(yt):
    res = yt.channels().list(
        part="snippet,statistics",
        mine=True,
        maxResults=1
    ).execute()
    ch = res["items"][0]
    stats = ch["statistics"]
    return {
        "subscribers": int(stats.get("subscriberCount", 0)),
        "views":       int(stats.get("viewCount", 0)),
        "videos":      int(stats.get("videoCount", 0)),
    }


def log_snapshot():
    print("Connecting to YouTube...")
    yt = get_youtube_service_with_fallback()
    stats = fetch_stats(yt)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log = load_log()

    # Don't double-log same day
    if log and log[-1]["date"] == today:
        print(f"  Already logged today ({today}) — updating snapshot.")
        log[-1] = {"date": today, **stats}
    else:
        log.append({"date": today, **stats})

    save_log(log)

    print(f"\n  📅 {today}")
    print(f"  👥 Subscribers : {stats['subscribers']:,}")
    print(f"  👁  Views       : {stats['views']:,}")
    print(f"  🎵 Videos      : {stats['videos']:,}")
    print(f"\n  Saved to growth_log.json ✓")


def print_report():
    log = load_log()
    if not log:
        print("No data yet — run `python track_growth.py` first.")
        return

    baseline = log[0]
    latest   = log[-1]
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Days relative to birthday milestone
    goal_dt   = datetime.strptime(GOAL_DATE, "%Y-%m-%d")
    today_dt  = datetime.strptime(today, "%Y-%m-%d")
    days_diff = (goal_dt - today_dt).days
    days_in   = len(log)
    past_goal = days_diff < 0
    days_left = abs(days_diff)

    sub_gain   = latest["subscribers"] - baseline["subscribers"]
    view_gain  = latest["views"]       - baseline["views"]
    video_gain = latest["videos"]      - baseline["videos"]

    # Daily averages
    avg_subs   = sub_gain   / days_in if days_in > 1 else 0
    avg_views  = view_gain  / days_in if days_in > 1 else 0
    avg_videos = video_gain / days_in if days_in > 1 else 0

    # Projections by June 25th
    proj_subs   = latest["subscribers"] + int(avg_subs   * days_left)
    proj_views  = latest["views"]       + int(avg_views  * days_left)
    proj_videos = latest["videos"]      + int(avg_videos * days_left)

    print(f"\n{'='*52}")
    print(f"  📈 LEEKTHATSFY3 — GROWTH REPORT")
    print(f"  {baseline['date']}  →  {latest['date']}")
    print(f"{'='*52}")
    print(f"  {'':20}  {'START':>8}  {'NOW':>8}  {'GAINED':>8}")
    print(f"  {'─'*48}")
    print(f"  {'👥 Subscribers':20}  {baseline['subscribers']:>8,}  {latest['subscribers']:>8,}  {sub_gain:>+8,}")
    print(f"  {'👁  Views':20}  {baseline['views']:>8,}  {latest['views']:>8,}  {view_gain:>+8,}")
    print(f"  {'🎵 Videos':20}  {baseline['videos']:>8,}  {latest['videos']:>8,}  {video_gain:>+8,}")
    print(f"{'─'*52}")
    print(f"  📅 Days tracked  : {days_in}")
    if past_goal:
        print(f"  🎂 June 25th was {days_left} days ago — still grinding!")
    else:
        print(f"  ⏳ Days to 🎂 June 25th : {days_left}")
    print(f"{'─'*52}")
    if past_goal:
        # Find birthday snapshot if it exists
        bday_entry = next((e for e in log if e["date"] == GOAL_DATE), None)
        if bday_entry:
            print(f"  🎂 BIRTHDAY SNAPSHOT (June 25th)")
            print(f"  {'👥 Subscribers':20}  {bday_entry['subscribers']:>8,}")
            print(f"  {'👁  Views':20}  {bday_entry['views']:>8,}")
            print(f"  {'🎵 Videos':20}  {bday_entry['videos']:>8,}")
        else:
            print(f"  🎂 JUNE 25TH PROJECTION (estimated)")
            print(f"  {'👥 Subscribers':20}  {proj_subs:>8,}")
            print(f"  {'👁  Views':20}  {proj_views:>8,}")
            print(f"  {'🎵 Videos':20}  {proj_videos:>8,}")
    else:
        print(f"  🔮 PROJECTED BY JUNE 25TH")
        print(f"  {'👥 Subscribers':20}  {proj_subs:>8,}")
        print(f"  {'👁  Views':20}  {proj_views:>8,}")
        print(f"  {'🎵 Videos':20}  {proj_videos:>8,}")
    print(f"{'='*52}\n")

    # Full history
    print(f"  📋 DAILY LOG")
    print(f"  {'─'*36}")
    for entry in log:
        print(f"  {entry['date']}  |  {entry['subscribers']:>6,} subs  |  {entry['views']:>8,} views  |  {entry['videos']:>4,} videos")
    print(f"{'='*52}\n")


if __name__ == "__main__":
    if "--report" in sys.argv:
        print_report()
    else:
        log_snapshot()

"""
daily_dispatch.py

Runs nightly via LaunchAgent. Uploads any unuploaded beats from
schedule_config.json whose publishAt time hasn't passed yet.
Skips beats already in uploads_log.json.

Each beat is uploaded with its exact scheduled publishAt time.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT        = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "schedule_config.json"
LOG_FILE    = ROOT / "uploads_log.json"
PYTHON      = str(ROOT / ".venv/bin/python3.14")
UPLOAD_PY   = str(ROOT / "upload.py")

def main():
    config = json.loads(CONFIG_FILE.read_text())
    schedule = config["schedule"]

    log = {}
    if LOG_FILE.exists():
        log = json.loads(LOG_FILE.read_text())

    now = datetime.now(tz=timezone.utc)

    pending = []
    for stem, publish_at in schedule.items():
        if stem in log:
            continue  # already uploaded
        dt = datetime.fromisoformat(publish_at)
        if dt > now:  # only future slots
            pending.append((stem, publish_at, dt))

    if not pending:
        print("daily_dispatch: nothing to upload today.")
        return

    # Sort by publish time, upload next 6 (YouTube daily quota ~6)
    pending.sort(key=lambda x: x[2])
    batch = pending[:6]

    print(f"daily_dispatch: uploading {len(batch)} beats")
    for stem, publish_at, dt in batch:
        print(f"  {stem} → {publish_at}")
        result = subprocess.run(
            [PYTHON, UPLOAD_PY,
             "--only", stem,
             "--schedule-at", publish_at],
            cwd=str(ROOT),
            capture_output=False
        )
        if result.returncode != 0:
            print(f"  ERROR uploading {stem}, stopping batch.")
            sys.exit(1)

    print("daily_dispatch: done.")

if __name__ == "__main__":
    main()

#!/bin/bash
# ============================================================
#  quota_reset_batch_day2.sh
#  Day 2 runner — picks up any uploads that hit quota on day 1
#  upload.py's --skip-uploaded logic handles deduplication
# ============================================================

set -e
cd /Users/fyefye/yt_automation
PYTHON="/Users/fyefye/yt_automation/.venv/bin/python3.14"

echo "============================================"
echo "  Day 2 Quota Reset Upload Runner"
echo "  Started: $(date)"
echo "============================================"
echo ""

# These will be automatically skipped if already uploaded on day 1
BEATS_BK=("late_night:2026-03-25T11:00:00-05:00"
           "wait_on_me:2026-03-26T11:00:00-05:00"
           "never_came:2026-03-27T11:00:00-05:00"
           "all_of_you:2026-03-28T11:00:00-05:00")

BEATS_SR=("rager_boy_146:2026-03-19T18:00:00-05:00"
           "papi:2026-03-20T18:00:00-05:00"
           "back:2026-03-21T18:00:00-05:00"
           "my_fault:2026-03-22T18:00:00-05:00"
           "picky:2026-03-23T18:00:00-05:00"
           "real_right:2026-03-24T18:00:00-05:00"
           "wut_u_on:2026-03-25T18:00:00-05:00"
           "kiss_my_ass:2026-03-26T18:00:00-05:00"
           "twerk:2026-03-27T18:00:00-05:00"
           "go_gooo:2026-03-28T18:00:00-05:00")

echo "── Uploading remaining BiggKutt8 beats ──"
for entry in "${BEATS_BK[@]}"; do
    stem="${entry%%:*}"
    sched="${entry#*:}"
    echo "  $stem -> $sched"
    $PYTHON upload.py --only "$stem" --schedule-at "$sched" || echo "  [SKIP/FAIL] $stem"
done

echo ""
echo "── Uploading remaining Sexyy Red beats ──"
for entry in "${BEATS_SR[@]}"; do
    stem="${entry%%:*}"
    sched="${entry#*:}"
    echo "  $stem -> $sched"
    $PYTHON upload.py --only "$stem" --schedule-at "$sched" || echo "  [SKIP/FAIL] $stem"
done

echo ""
echo "============================================"
echo "  Day 2 complete: $(date)"
echo "============================================"

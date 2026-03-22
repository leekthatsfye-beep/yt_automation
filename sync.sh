#!/bin/bash
# FY3 Sync — push or pull changes between Mac and PC
# Usage: ./sync.sh push   (save and upload your changes)
#        ./sync.sh pull   (download changes from the other machine)
#        ./sync.sh        (pull then push — full sync)

cd "$(dirname "$0")"

case "${1:-sync}" in
  push)
    echo "Pushing changes..."
    git add -A
    git commit -m "sync: $(date '+%m/%d %H:%M') from $(hostname -s)" 2>/dev/null || echo "Nothing new to commit"
    git push
    echo "Done."
    ;;
  pull)
    echo "Pulling changes..."
    git pull --rebase
    echo "Done."
    ;;
  sync|*)
    echo "Syncing..."
    git pull --rebase
    git add -A
    git commit -m "sync: $(date '+%m/%d %H:%M') from $(hostname -s)" 2>/dev/null || echo "Nothing new to commit"
    git push
    echo "Done."
    ;;
esac

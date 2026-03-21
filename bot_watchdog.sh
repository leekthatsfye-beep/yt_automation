#!/bin/bash
# bot_watchdog.sh — runs every 5 minutes via LaunchAgent
# If bot is dead, sends Telegram message and restarts it

BOT_TOKEN="8357976330:AAGnBdkVgqnk-_YhZLMCvkwDhIuYciZTFhM"
CHAT_ID="5594051609"  # your Telegram user ID
LOG="/Users/fyefye/yt_automation/logs/watchdog.log"

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" \
        -d "text=$1" \
        -d "parse_mode=Markdown" > /dev/null 2>&1
}

# Check if bot process is running
if ! pgrep -f "telegram_bot.py" > /dev/null; then
    echo "$(date): Bot not running — attempting restart" >> "$LOG"

    # Restart via LaunchAgent
    launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.ytautomation.telegrambot.plist 2>/dev/null
    sleep 2
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ytautomation.telegrambot.plist
    sleep 5

    if pgrep -f "telegram_bot.py" > /dev/null; then
        echo "$(date): Bot restarted successfully" >> "$LOG"
        send_telegram "✅ *Bot Watchdog:* Bot crashed and was auto-restarted. All good."
    else
        echo "$(date): Bot FAILED to restart" >> "$LOG"
        send_telegram "🚨 *Bot Watchdog ALERT:* Bot crashed and FAILED to restart. Manual intervention needed."
    fi
fi

# Check if TeamViewer is running
if ! pgrep -x "TeamViewer" > /dev/null; then
    echo "$(date): TeamViewer not running — starting it" >> "$LOG"
    open -a TeamViewer
fi

# Check if caffeinate is running
if ! pgrep -x "caffeinate" > /dev/null; then
    echo "$(date): caffeinate not running — starting it" >> "$LOG"
    /usr/bin/caffeinate -i &
fi

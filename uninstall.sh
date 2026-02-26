#!/bin/bash

PLIST_NAME="com.odoo-launcher.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "=== Odoo Launcher 제거 ==="

if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm "$PLIST_PATH"
    echo "LaunchAgent 제거됨"
else
    echo "LaunchAgent가 존재하지 않습니다."
fi

echo "=== 제거 완료 ==="
echo "  projects.json과 app.py는 유지됩니다."

#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PY="$SCRIPT_DIR/app.py"
PLIST_NAME="com.odoo-launcher.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"
LOG_FILE="$SCRIPT_DIR/launcher.log"

echo "=== Odoo Launcher 설치 ==="
echo ""

# 1. Detect Python 3
if command -v python3 &>/dev/null; then
    DEFAULT_PYTHON="$(command -v python3)"
else
    DEFAULT_PYTHON=""
fi

read -rp "Python 3 경로 [$DEFAULT_PYTHON]: " PYTHON_PATH
PYTHON_PATH="${PYTHON_PATH:-$DEFAULT_PYTHON}"

if [ ! -f "$PYTHON_PATH" ]; then
    echo "Error: Python not found at $PYTHON_PATH"
    exit 1
fi

echo "  Python: $PYTHON_PATH"

# 2. Launcher port
read -rp "런처 포트 [9069]: " LAUNCHER_PORT
LAUNCHER_PORT="${LAUNCHER_PORT:-9069}"
echo "  Port: $LAUNCHER_PORT"

# 3. Create projects.json if not exists
if [ ! -f "$SCRIPT_DIR/projects.json" ]; then
    cp "$SCRIPT_DIR/projects.example.json" "$SCRIPT_DIR/projects.json" 2>/dev/null || echo "[]" > "$SCRIPT_DIR/projects.json"
    echo "  projects.json 생성됨 (설정 필요)"
fi

# 4. Unload existing agent
if launchctl list | grep -q "com.odoo-launcher"; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    echo "  기존 LaunchAgent 해제됨"
fi

# 5. Generate LaunchAgent plist
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.odoo-launcher</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$APP_PY</string>
        <string>--port</string>
        <string>$LAUNCHER_PORT</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>

    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>
</dict>
</plist>
EOF

echo "  LaunchAgent 생성됨: $PLIST_PATH"

# 6. Load agent
launchctl load "$PLIST_PATH"
sleep 1

if lsof -i ":$LAUNCHER_PORT" -t &>/dev/null; then
    echo ""
    echo "=== 설치 완료 ==="
    echo "  접속: http://127.0.0.1:$LAUNCHER_PORT"
    echo "  설정: $SCRIPT_DIR/projects.json"
    echo "  제거: bash $SCRIPT_DIR/uninstall.sh"
else
    echo ""
    echo "Warning: 서버가 시작되지 않았습니다. 로그를 확인하세요:"
    echo "  tail -f $LOG_FILE"
fi

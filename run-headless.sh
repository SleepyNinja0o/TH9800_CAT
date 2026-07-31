#!/usr/bin/env bash
# TH9800_CAT — headless server launcher
# Reads config.txt for device/baud, resolves the serial port, and starts
# the TCP server without GUI.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/venv/bin/python"
CONFIG="$SCRIPT_DIR/config.txt"

# Read a value from config.txt
read_cfg() {
    local key="$1" default="$2"
    local val
    val="$(grep -m1 "^${key}=" "$CONFIG" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//')"
    if [ -z "$val" ]; then echo "$default"; else echo "$val"; fi
}

BAUD="$(read_cfg baud_rate 19200)"
DEVICE_NAME="$(read_cfg device "")"
HOST="$(read_cfg host 0.0.0.0)"
PORT="$(read_cfg port 9800)"
PASSWORD="$(read_cfg password "")"

# Also check gateway config for port/password overrides
GW_CONFIG="$HOME/Downloads/radio-gateway/gateway_config.txt"
if [ -f "$GW_CONFIG" ]; then
    GW_PORT="$(grep -m1 '^[[:space:]]*CAT_PORT' "$GW_CONFIG" 2>/dev/null \
        | sed 's/^[^=]*=[[:space:]]*//' | sed 's/[[:space:]]*#.*//' | tr -d "'\"")"
    GW_PASS="$(grep -m1 '^[[:space:]]*CAT_PASSWORD' "$GW_CONFIG" 2>/dev/null \
        | sed 's/^[^=]*=[[:space:]]*//' | sed 's/[[:space:]]*#.*//' | tr -d "'\"")"
    [ -n "$GW_PORT" ] && PORT="$GW_PORT"
    [ -n "$GW_PASS" ] && PASSWORD="$GW_PASS"
fi

# Resolve serial device by matching description
COMPORT=""
if [ -n "$DEVICE_NAME" ]; then
    COMPORT="$("$PYTHON" -c "
import serial.tools.list_ports
for p in serial.tools.list_ports.comports():
    if '$DEVICE_NAME' in p.description:
        print(p.device)
        break
" 2>/dev/null)"
fi

if [ -z "$COMPORT" ]; then
    echo "ERROR: No serial device matching '$DEVICE_NAME' found"
    echo "Available ports:"
    "$PYTHON" -c "import serial.tools.list_ports; [print(f'  {p.device}: {p.description}') for p in serial.tools.list_ports.comports()]" 2>/dev/null
    exit 1
fi

echo "Starting headless: $COMPORT @ $BAUD, port $PORT"
cd "$SCRIPT_DIR"
exec "$PYTHON" -u TH9800_CAT.py \
    -s -c "$COMPORT" -b "$BAUD" \
    -p "$PASSWORD" -sH "$HOST" -sP "$PORT"

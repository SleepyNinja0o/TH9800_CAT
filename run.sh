#!/usr/bin/env bash
ARCH="$(uname -m)"

cd "$(dirname "${BASH_SOURCE[0]}")"

case "$ARCH" in
    armv6l)
        exec "$(dirname "${BASH_SOURCE[0]}")/venv/bin/python" TH9800_CAT.py "$@"
        #exec "MESA_GL_VERSION_OVERRIDE=4.5 MESA_GLSL_VERSION_OVERRIDE=450 $(dirname "${BASH_SOURCE[0]}")/venv/bin/python" TH9800_CAT.py "$@"
        ;;
    armv7l|aarch64|arm64)
        exec "$(dirname "${BASH_SOURCE[0]}")/venv/bin/python" TH9800_CAT.py "$@"
        ;;
    *)
        echo "Unknown architecture ($ARCH)..."
        exit 1
        ;;
esac
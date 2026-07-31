#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
ARCH="$(uname -m)"

echo "=== TH9800_CAT Installer ==="
echo "Architecture : $ARCH"
echo "Project dir  : $SCRIPT_DIR"
echo ""

# ── 1. Python 3 sanity check ────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.9+ and re-run."
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python version: $PY_VER"

# ── Detect package manager ────────────────────────────────────────────────
if command -v pacman &>/dev/null; then
    PKG_MGR="pacman"
elif command -v apt-get &>/dev/null; then
    PKG_MGR="apt"
else
    PKG_MGR="unknown"
fi

pkg_installed() {
    case "$PKG_MGR" in
        pacman)  pacman -Qi "$1" &>/dev/null ;;
        apt)     dpkg -s "$1" &>/dev/null 2>&1 ;;
        *)       return 1 ;;
    esac
}

pkg_install() {
    case "$PKG_MGR" in
        pacman)  sudo pacman -S --needed --noconfirm "$@" ;;
        apt)     sudo apt-get install -y "$@" ;;
        *)       echo "ERROR: No supported package manager found."; exit 1 ;;
    esac
}

# ── 2. Ensure python3-venv is available, then create virtual environment ────
echo ""
echo "[1/4] Creating virtual environment at $VENV_DIR ..."

if [ "$PKG_MGR" = "apt" ]; then
    # On Debian/Ubuntu, python3-venv ships in a separate package.
    if pkg_installed "python${PY_VER}-venv"; then
        echo "  python${PY_VER}-venv already installed."
    else
        echo "  Installing python${PY_VER}-venv ..."
        pkg_install "python${PY_VER}-venv"
    fi
else
    echo "  venv is included with python3 on this distro."
fi

# Treat a venv with no pip binary as broken (e.g. from a failed prior run)
if [ -d "$VENV_DIR" ] && [ ! -f "$VENV_DIR/bin/pip" ]; then
    echo "  Incomplete venv detected — removing and recreating ..."
    rm -rf "$VENV_DIR"
fi

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
else
    echo "  Virtual environment already exists, skipping creation."
fi

PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python"

"$PIP" install --upgrade pip --quiet

# ── 3. System-level dependencies (Linux only, needed by dearpygui) ──────────
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo ""
    echo "[2/4] Checking system dependencies for dearpygui ..."

    if [ "$PKG_MGR" = "pacman" ]; then
        SYS_PKGS=(glu mesa libxrandr libxinerama libxcursor libxi)
    else
        SYS_PKGS=(libglu1-mesa libgl1-mesa-dev libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev)
    fi

    MISSING_PKGS=()
    for pkg in "${SYS_PKGS[@]}"; do
        if ! pkg_installed "$pkg"; then
            MISSING_PKGS+=("$pkg")
        fi
    done
    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        echo "  Installing missing system packages: ${MISSING_PKGS[*]}"
        pkg_install "${MISSING_PKGS[@]}"
    else
        echo "  All system dependencies already present."
    fi
fi

# ── 4. Install Python packages ───────────────────────────────────────────────
echo ""
echo "[3/4] Installing Python packages ..."

# asyncio is part of the Python standard library (since 3.4).
# The standalone PyPI package (asyncio==3.4.3) is deprecated, conflicts with
# the built-in module on Python 3.5+, and fails to install on Python 3.12+.
# It is intentionally skipped here.
echo "  Skipping 'asyncio' — already built into Python $PY_VER (stdlib)"

"$PIP" install "pyserial==3.5"
"$PIP" install "pyserial-asyncio==0.6"

# ── 5. dearpygui — handle prebuilt vs. source-build ─────────────────────────
echo ""
echo "[4/4] Installing dearpygui ..."

install_dearpygui_prebuilt() {
    # Try the pinned version first; fall back to latest if no wheel exists for
    # this Python version (e.g. cp313 wheel missing for 2.0.0).
    if "$PIP" install "dearpygui==2.0.0" 2>/dev/null; then
        echo "  dearpygui 2.0.0 installed successfully."
    else
        echo "  No prebuilt wheel for dearpygui 2.0.0 on Python $PY_VER."
        echo "  Falling back to latest available release ..."
        "$PIP" install dearpygui
        DPG_VER=$("$PYTHON" -c "import dearpygui; print(dearpygui.__version__)" 2>/dev/null || echo "unknown")
        echo "  dearpygui $DPG_VER installed."
    fi
}

install_dearpygui_from_wheel() {
    # Check for a cached local wheel before building from source.
    # Looks in project dist/ and ~/dist/ for a matching platform wheel.
    local wheel=""
    for dir in "$SCRIPT_DIR/dist" "$HOME/dist"; do
        if [ -d "$dir" ]; then
            wheel=$(find "$dir" -name "dearpygui-*-$PLAT.whl" -print -quit 2>/dev/null)
            [ -n "$wheel" ] && break
        fi
    done

    if [ -n "$wheel" ]; then
        echo "  Found cached wheel: $wheel"
        "$PIP" install "$wheel"
        echo "  dearpygui installed from cached wheel."
        return 0
    fi
    return 1
}

install_dearpygui_from_source() {
    echo "  ARM detected ($ARCH) — building dearpygui from source."
    echo "  This may take several minutes on lower-end boards."

    # Build deps
    if [ "$PKG_MGR" = "pacman" ]; then
        pkg_install git cmake python glu mesa libxrandr libxinerama libxcursor libxi
    else
        pkg_install git cmake python3 python3-dev \
            libglu1-mesa-dev libgl1-mesa-dev \
            libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev
    fi

    BUILD_TMP=$(mktemp -d)
    # Clean up build directory on exit regardless of success or failure
    cleanup() { rm -rf "$BUILD_TMP"; }
    trap cleanup EXIT

    git clone --recursive https://github.com/hoffstadt/DearPyGui "$BUILD_TMP/DearPyGui"

    cd "$BUILD_TMP/DearPyGui"

    # setup.py must be run as a script, not with -m
    "$PYTHON" setup.py bdist_wheel --plat-name "$PLAT" --dist-dir "$BUILD_TMP/dist"

    # Cache the wheel in the project dist/ directory for future installs
    mkdir -p "$SCRIPT_DIR/dist"
    cp "$BUILD_TMP"/dist/dearpygui-*.whl "$SCRIPT_DIR/dist/"
    echo "  Wheel cached in $SCRIPT_DIR/dist/"

    "$PIP" install "$BUILD_TMP"/dist/dearpygui-*.whl

    cd "$SCRIPT_DIR"
    echo "  dearpygui built and installed from source."
}

case "$ARCH" in
    x86_64|i686|amd64)
        # Prebuilt wheels are available for x86; try pinned version, fall back to latest.
        PLAT="linux_x86_64"
        install_dearpygui_prebuilt
        ;;
    armv7l)
        PLAT="linux_armv7l"
        install_dearpygui_from_wheel || install_dearpygui_from_source
        ;;
    aarch64|arm64)
        PLAT="linux_aarch64"
        install_dearpygui_from_wheel || install_dearpygui_from_source
        ;;
    *)
        echo "  Unknown architecture ($ARCH), attempting prebuilt install ..."
        PLAT="unknown"
        install_dearpygui_prebuilt
        ;;
esac

# ── Create run.sh wrapper ─────────────────────────────────────────────────────
cat > "$SCRIPT_DIR/run.sh" << EOF
#!/usr/bin/env bash
cd "\$(dirname "\${BASH_SOURCE[0]}")"
exec "\$(dirname "\${BASH_SOURCE[0]}")/venv/bin/python" TH9800_CAT.py "\$@"
EOF
chmod +x "$SCRIPT_DIR/run.sh"

# ── Install systemd service ───────────────────────────────────────────────────
echo ""
echo "[5/5] Installing systemd service ..."

SERVICE_FILE="/etc/systemd/system/th9800-cat.service"
CURRENT_USER="$(whoami)"
HEADLESS_SH="$SCRIPT_DIR/run-headless.sh"

sudo tee "$SERVICE_FILE" > /dev/null << SVCEOF
[Unit]
Description=TH-9800 CAT Control Server (headless)
After=network.target
Before=radio-gateway.service

[Service]
Type=simple
User=$CURRENT_USER
Group=$CURRENT_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$HEADLESS_SH
KillMode=control-group
KillSignal=SIGTERM
TimeoutStopSec=10

Restart=on-failure
RestartSec=5

StandardOutput=journal
StandardError=journal
SyslogIdentifier=th9800-cat

# Serial port access
SupplementaryGroups=uucp

Environment=HOME=$HOME

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable th9800-cat.service
echo "  Service installed and enabled: th9800-cat.service"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "=== Installation complete ==="
echo ""
echo "To run standalone:  ./run.sh"
echo "As a service:       sudo systemctl start th9800-cat"
echo "View logs:          journalctl -u th9800-cat -f"

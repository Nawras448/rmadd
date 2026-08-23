#!/usr/bin/env bash
set -e

INSTALL_DIR="$HOME/.local/share/rmadd"
BIN_DIR="$HOME/.local/bin"

echo "🚀 Installing rmadd..."

# ------------------------------------------------------ prerequisites ----

if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 is required."
    echo "   Install it with: sudo apt install python3"
    exit 1
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
    echo "❌ python3 venv support is missing."
    echo "   Install it with: sudo apt install python3-venv"
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    echo "❌ git is required (the package is installed from its Git repository)."
    echo "   Install it with: sudo apt install git"
    exit 1
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

# ------------------------------------------- environment & installation --

echo "📦 Creating isolated environment & installing..."
if ! python3 -m venv "$INSTALL_DIR/venv"; then
    echo "❌ Failed to create the virtual environment."
    echo "   On Debian/Ubuntu this usually means: sudo apt install python3-venv"
    exit 1
fi

"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet --no-cache-dir --upgrade git+https://github.com/Nawras448/rmadd.git

# ------------------------------------------------------------ launcher ---

echo "🔧 Creating launcher..."
ln -sf "$INSTALL_DIR/venv/bin/rmadd" "$BIN_DIR/rmadd"

echo "✅ rmadd installed successfully!"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "⚠️  Add $BIN_DIR to your PATH by running:"
    echo '    export PATH="$HOME/.local/bin:$PATH"'
fi

echo "🎉 Run 'rmadd' to start!"
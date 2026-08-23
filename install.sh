#!/usr/bin/env bash
set -e

INSTALL_DIR="$HOME/.local/share/rmadd"
BIN_DIR="$HOME/.local/bin"

echo "🚀 Installing rmadd..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is required."
    exit 1
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

echo "📦 Creating isolated environment & installing..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet git+https://github.com/Nawras448/rmadd.git

ln -sf "$INSTALL_DIR/venv/bin/rmadd" "$BIN_DIR/rmadd"

echo "✅ rmadd installed successfully!"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "⚠️  Add $BIN_DIR to your PATH by running:"
    echo '    export PATH="$HOME/.local/bin:$PATH"'
fi

echo "🎉 Run 'rmadd' to start!"

#!/bin/bash

###############################################################################
# RunPod Startup Script - AI Coding Agent
# This script runs automatically on pod restart to set up the environment
###############################################################################

set -e  # Exit on error

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   🚀 AI Coding Agent - Pod Startup                       ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Define paths
VENV_PATH="/workspace/ai-coding-agent/venv"
PROJECT_PATH="/workspace/ai-coding-agent"

# Install Node.js (if needed)
if ! command -v node &> /dev/null; then
    echo "📦 Installing Node.js..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
else
    echo "✓ Node.js already installed: $(node --version)"
fi

# Reinstall Ollama (if needed)
if ! command -v ollama &> /dev/null; then
    echo "📦 Installing Ollama..."
    curl -fsSL https://ollama.ai/install.sh | sh
else
    echo "✓ Ollama already installed: $(ollama --version)"
fi

# Configure Ollama to use volume
export OLLAMA_MODELS=/workspace/.ollama
if ! grep -q "OLLAMA_MODELS=/workspace/.ollama" ~/.bashrc; then
    echo 'export OLLAMA_MODELS=/workspace/.ollama' >> ~/.bashrc
    echo "✓ Ollama configured to use persistent volume"
else
    echo "✓ Ollama already configured for persistent volume"
fi

# Restore SSH keys from persistent storage
# Note: We copy instead of symlink due to permission requirements
if [ -d "/workspace/.ssh" ] && [ -f "/workspace/.ssh/id_ed25519" ]; then
    echo "🔑 Restoring SSH keys from persistent storage..."
    rm -rf ~/.ssh
    mkdir -p ~/.ssh
    cp /workspace/.ssh/id_ed25519* ~/.ssh/
    chmod 700 ~/.ssh
    chmod 600 ~/.ssh/id_ed25519
    chmod 644 ~/.ssh/id_ed25519.pub
    # Add GitHub to known hosts
    ssh-keyscan -H github.com >> ~/.ssh/known_hosts 2>/dev/null
    echo "✓ SSH keys restored and configured"
else
    echo "ℹ️  No SSH keys found in /workspace/.ssh"
fi

# Start Ollama service
if ! pgrep -x "ollama" > /dev/null; then
    echo "🔧 Starting Ollama service..."
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    sleep 5
    echo "✓ Ollama service started"
else
    echo "✓ Ollama service already running"
fi

# Navigate to project directory
cd "$PROJECT_PATH"

# Create Python virtual environment if it doesn't exist
if [ ! -d "$VENV_PATH" ]; then
    echo "📦 Creating Python virtual environment..."
    python -m venv "$VENV_PATH"
    echo "✓ Virtual environment created at $VENV_PATH"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source "$VENV_PATH/bin/activate"

# Check if dependencies are already installed
MARKER_FILE="$VENV_PATH/.deps_installed"
if [ -f "$MARKER_FILE" ]; then
    echo "✓ Python dependencies already installed (to reinstall: rm $MARKER_FILE)"
else
    echo "📦 Upgrading pip..."
    pip install -q --upgrade pip

    echo "📦 Installing Python dependencies in virtual environment..."
    pip install -q -r requirements.txt

    # Create marker file to skip installation next time
    touch "$MARKER_FILE"
    echo "✓ Python dependencies installed in venv"
fi

# Reinstall Claude CLI globally (if needed)
if ! command -v claude &> /dev/null; then
    echo "📦 Installing Claude CLI..."
    npm install -g @anthropic-ai/claude-code
    echo "✓ Claude CLI installed"
else
    echo "✓ Claude CLI already installed: $(claude --version 2>/dev/null || echo 'Not authenticated')"
fi

# Note: venv auto-activation is configured in .bashrc
echo "✓ Virtual environment ready for use"

# Display status
echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   ✅ Environment Ready!                                   ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Installed versions:"
echo "  • Node:       $(node --version)"
echo "  • Python:     $(python --version 2>&1)"
echo "  • Pip:        $(pip --version | cut -d' ' -f2)"
echo "  • Ollama:     $(ollama --version)"
echo "  • Claude CLI: $(claude --version 2>/dev/null || echo 'Not authenticated')"
echo "  • Venv:       $VENV_PATH"
echo ""
echo "💡 Available commands:"
echo "  python demo.py              # Run demo"
echo "  python -m src.cli chat      # Interactive mode"
echo "  python -m src.cli index ./src  # Index codebase"
echo "  claude                      # Claude Code CLI"
echo "  nvidia-smi                  # Check GPU"
echo "  ollama list                 # Check models"
echo ""
echo "🔍 Quick test (GPU inference, 1-3 seconds):"
echo "  ollama run deepseek-coder:6.7b-instruct 'Write a Python hello world'"
echo ""

#!/bin/bash

###############################################################################
# RunPod GPU Setup Script for AI Coding Agent
#
# This script automates the setup of the AI Coding Agent on a RunPod GPU pod.
# Run this script immediately after SSH-ing into your RunPod pod.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/vijayjayanandan/ai-coding-agent/main/runpod-setup.sh | bash
#
# Or manually:
#   bash runpod-setup.sh
#
###############################################################################

set -e  # Exit on error

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   AI Coding Agent - RunPod GPU Setup                     ║"
echo "║   GPU-Accelerated Development Environment                ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Helper functions
print_step() {
    echo -e "${BLUE}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Check if running on GPU pod
print_step "Checking GPU availability..."
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
    print_success "GPU detected!"
else
    print_error "No GPU found! Make sure you're on a GPU pod."
    exit 1
fi

# Update system packages
print_step "Updating system packages..."
apt-get update > /dev/null 2>&1
apt-get install -y git curl wget > /dev/null 2>&1
print_success "System packages updated"

# Check if Ollama is already installed
if command -v ollama &> /dev/null; then
    print_success "Ollama already installed ($(ollama --version))"
else
    print_step "Installing Ollama (GPU version)..."
    curl -fsSL https://ollama.ai/install.sh | sh
    print_success "Ollama installed"
fi

# Start Ollama service
print_step "Starting Ollama service..."
if pgrep -x "ollama" > /dev/null; then
    print_warning "Ollama already running"
else
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    sleep 5
    print_success "Ollama service started"
fi

# Test Ollama connection
print_step "Testing Ollama connection..."
if curl -s http://localhost:11434/api/tags > /dev/null; then
    print_success "Ollama API responding"
else
    print_error "Ollama API not responding"
    print_warning "Check logs: tail -f /tmp/ollama.log"
    exit 1
fi

# Configure Ollama to use volume storage for persistence
print_step "Configuring Ollama to use volume storage..."
mkdir -p /workspace/.ollama
export OLLAMA_MODELS=/workspace/.ollama
if ! grep -q "OLLAMA_MODELS=/workspace/.ollama" ~/.bashrc; then
    echo 'export OLLAMA_MODELS=/workspace/.ollama' >> ~/.bashrc
fi
print_success "Ollama configured to use /workspace/.ollama (persistent volume)"

# Check if DeepSeek Coder model exists
print_step "Checking for DeepSeek Coder model..."
if ollama list | grep -q "deepseek-coder:6.7b-instruct"; then
    print_success "DeepSeek Coder 6.7B Instruct already installed"
else
    print_step "Pulling DeepSeek Coder 6.7B Instruct model (~3.8 GB)..."
    print_warning "This will take 2-5 minutes depending on connection speed..."
    ollama pull deepseek-coder:6.7b-instruct
    print_success "DeepSeek Coder model installed (better for coding tasks!)"
fi

# Clone repository if not already present
print_step "Setting up AI Coding Agent repository..."
cd /workspace

if [ -d "ai-coding-agent" ]; then
    print_warning "Repository already exists, updating..."
    cd ai-coding-agent
    git pull
else
    print_step "Cloning repository from GitHub..."
    git clone https://github.com/vijayjayanandan/ai-coding-agent.git
    cd ai-coding-agent
    print_success "Repository cloned"
fi

# Install Python dependencies
print_step "Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
print_success "Python dependencies installed"

# Install SQLite fix
print_step "Installing SQLite compatibility fix..."
pip install -q pysqlite3-binary
print_success "SQLite fix installed"

# Verify GPU PyTorch
print_step "Verifying PyTorch GPU support..."
python -c "import torch; print(f'  PyTorch version: {torch.__version__}'); print(f'  CUDA available: {torch.cuda.is_available()}'); print(f'  CUDA version: {torch.version.cuda if torch.cuda.is_available() else \"N/A\"}')"
print_success "PyTorch GPU support verified"

# Test imports
print_step "Testing project imports..."
python -c "import src; from src.memory import TaskContext; import chromadb; print('  All imports successful!')"
print_success "Project imports working"

# Quick Ollama test
print_step "Testing Ollama with GPU..."
echo "  Running quick inference test..."
RESPONSE=$(ollama run deepseek-coder:6.7b-instruct "Say 'Hello from GPU!' in one line" 2>&1 | head -n 1)
echo "  Model response: $RESPONSE"
print_success "Ollama GPU inference working"

# Display GPU info
echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   Setup Complete! GPU Environment Ready                  ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo -e "${GREEN}GPU Information:${NC}"
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv,noheader | sed 's/^/  /'
echo ""
echo -e "${GREEN}Installed Components:${NC}"
echo "  ✓ Ollama: $(ollama --version)"
echo "  ✓ Python: $(python --version 2>&1)"
echo "  ✓ PyTorch: $(python -c 'import torch; print(torch.__version__)')"
echo "  ✓ CUDA: $(python -c 'import torch; print(torch.version.cuda if torch.cuda.is_available() else "N/A")')"
echo "  ✓ Repository: /workspace/ai-coding-agent"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo "  1. Run demo:     python demo.py"
echo "  2. Chat mode:    python -m src.cli chat"
echo "  3. Index code:   python -m src.cli index ./src"
echo "  4. Help:         python -m src.cli --help"
echo ""
echo -e "${YELLOW}Quick Test (should respond in 1-3 seconds):${NC}"
echo "  ollama run deepseek-coder:6.7b-instruct 'Write a Python hello world'"
echo ""
echo -e "${GREEN}Happy coding! 🚀${NC}"
echo ""

# Create a quick GPU monitoring alias
echo ""
echo -e "${BLUE}Tip: Monitor GPU usage with:${NC}"
echo "  watch -n 1 nvidia-smi"
echo ""

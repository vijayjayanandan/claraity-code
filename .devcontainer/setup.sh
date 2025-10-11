#!/bin/bash

echo "🚀 Setting up AI Coding Agent Dev Environment..."

# Update system
sudo apt-get update

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Ollama
echo "📦 Installing Ollama..."
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama service in background
echo "🔧 Starting Ollama service..."
nohup ollama serve > /tmp/ollama.log 2>&1 &

# Wait for Ollama to be ready
sleep 5

# Pull recommended model
echo "📥 Pulling CodeLlama 7B Instruct model..."
ollama pull codellama:7b-instruct

# Install Claude Code CLI
echo "📦 Installing Claude Code CLI..."
npm install -g @anthropic-ai/claude-code

echo "✅ Setup complete!"
echo ""
echo "🎉 Ready to use! Try:"
echo "   python -m src.cli chat        # AI Coding Agent"
echo "   python demo.py                # Demo"
echo "   claude                        # Claude Code CLI (use your Max subscription!)"

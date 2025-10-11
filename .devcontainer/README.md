# Dev Container Setup

## What This Does

This dev container provides a complete, isolated environment for testing the AI Coding Agent with:
- Python 3.11
- Ollama (local LLM runtime)
- CodeLlama 7B model
- All dependencies pre-installed

## Prerequisites

1. **Docker Desktop** - Install from https://www.docker.com/products/docker-desktop
2. **VS Code** - With "Dev Containers" extension
3. **Claude Code** (optional) - For AI assistance during testing

## Quick Start

### Option 1: VS Code (Recommended)

1. Open this folder in VS Code
2. Click "Reopen in Container" when prompted
3. Wait for setup to complete (~5-10 minutes)
4. Run: `python demo.py`

### Option 2: Command Line

```bash
# Build and start container
docker build -f .devcontainer/Dockerfile -t ai-coding-agent-dev .
docker run -it -v $(pwd):/workspace ai-coding-agent-dev

# Inside container
python -m src.cli chat
```

## What Gets Installed

- ✅ Python 3.11 with all dependencies
- ✅ Ollama LLM runtime
- ✅ CodeLlama 7B Instruct model (~4GB)
- ✅ All project dependencies
- ✅ Development tools (git, etc.)

## Testing Checklist

Once container is running:

```bash
# 1. Verify installation
python -c "import src; print('✓ Imports working')"

# 2. Check Ollama
ollama list  # Should show codellama:7b-instruct

# 3. Run demo
python demo.py

# 4. Try interactive mode
python -m src.cli chat

# 5. Test indexing
python -m src.cli index ./src

# 6. Single task
python -m src.cli task "Explain the memory system" --type explain
```

## Resource Requirements

- **RAM**: 8GB minimum, 16GB recommended
- **Disk**: 10GB for container + models
- **CPU**: Any modern CPU (GPU optional)

## Troubleshooting

### Container Build Fails
```bash
# Clear Docker cache
docker system prune -a
# Rebuild
code .  # Reopen in container
```

### Ollama Not Starting
```bash
# Inside container
ollama serve &
sleep 5
ollama list
```

### Out of Memory
```bash
# Use smaller model
ollama pull codellama:7b-code  # 3.8GB instead of 7B instruct
# Or reduce Docker memory limit in Docker Desktop settings
```

### Slow Performance
- Increase Docker CPU/RAM allocation
- Use quantized models (Q4, Q5)
- Close other applications

## Next Steps After Testing

1. **If tests pass**: Deploy to local machine
2. **If issues found**: Debug in isolated environment
3. **Iterate**: Make changes and test again
4. **Document**: Note any environment-specific issues

## Benefits of This Approach

✅ **Safe** - Won't affect your system
✅ **Reproducible** - Same environment every time
✅ **Fast iteration** - Quick rebuild if needed
✅ **CI/CD ready** - Can use same container in pipelines
✅ **Shareable** - Team members get identical setup

## Alternative: Test Locally First

If you prefer to test locally first:

```bash
# Install Ollama locally
# Windows: Download from https://ollama.ai
# Mac: brew install ollama
# Linux: curl -fsSL https://ollama.ai/install.sh | sh

# Pull model
ollama pull codellama:7b-instruct

# Install Python deps
pip install -r requirements.txt

# Test
python demo.py
```

Then later containerize for deployment.

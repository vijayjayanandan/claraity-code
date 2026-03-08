# Deployment Workflow & Docker Resource Guide

## 🎯 Recommended Workflow

### Option 1: Git Push → Container Clone (RECOMMENDED) ⭐

**Best for:**
- Version control
- Collaboration
- Backup
- Clean container state

**Workflow:**
```powershell
# 1. Commit and push your code
git add .
git commit -m "Complete AI coding agent implementation"
git push origin main

# 2. Start container (uses devcontainer)
code .
# Click "Reopen in Container"

# 3. Container automatically:
# - Mounts your local workspace
# - Has all your code
# - Ready to run immediately!
```

**How it works:**
- Devcontainer **mounts** your local folder into container
- Changes in container = changes on host (and vice versa)
- Automatically synced
- No manual copying needed!

### Option 2: Direct Mount (Already Configured) ✅

This is **already set up** in `.devcontainer/devcontainer.json`:

```json
"mounts": [
  "source=${localWorkspaceFolder},target=/workspace,type=bind,consistency=cached"
]
```

**What this means:**
- Your local `C:\Vijay\Learning\AI\ai-coding-agent` → Container `/workspace`
- **Bidirectional sync** - changes anywhere appear everywhere
- No git push/pull needed for container to see code
- But **still push to git** for version control!

### Recommended Flow:

```powershell
# ========================================
# Development Workflow (Best Practice)
# ========================================

# 1. Make changes locally in VS Code
# (Edit files, container sees them immediately)

# 2. Test in container terminal
python demo.py

# 3. Commit when ready
git add .
git commit -m "Add feature X"

# 4. Push to GitHub (backup + collaboration)
git push origin main

# 5. Continue developing
# Container always has latest code (mounted)
```

## 📊 Docker Desktop Resource Requirements

### Minimum Requirements (Will Work, Might Be Slow)
- **RAM**: 8 GB allocated to Docker
- **CPU**: 2 cores
- **Disk**: 20 GB free
- **Swap**: 2 GB

### Recommended for Smooth Operation
- **RAM**: 12 GB allocated to Docker
- **CPU**: 4+ cores
- **Disk**: 30 GB free
- **Swap**: 4 GB

### Optimal Performance
- **RAM**: 16 GB allocated to Docker
- **CPU**: 6+ cores
- **Disk**: 50 GB free
- **Swap**: 8 GB

## 🔧 How to Check & Configure Docker Resources

### Check Current Settings (Windows PowerShell)

```powershell
# Check Docker is running
docker info

# Check allocated resources
docker system info | Select-String -Pattern "CPUs|Total Memory"
```

### Configure in Docker Desktop

1. **Open Docker Desktop**
   - Right-click Docker icon in system tray
   - Select "Settings" or "Preferences"

2. **Go to Resources**
   - Click "Resources" in left sidebar
   - Adjust settings:

**Memory (RAM):**
```
For your system (if you have 16GB total):
Allocate: 10-12 GB to Docker
Leave: 4-6 GB for Windows
```

**CPUs:**
```
For your system (if you have 8 cores):
Allocate: 6 cores to Docker
Leave: 2 cores for Windows
```

**Disk:**
```
Disk image size: 60 GB minimum
Disk image location: SSD if available (much faster)
```

**Swap:**
```
Swap: 4 GB
```

3. **Click "Apply & Restart"**

### Verify Settings

```powershell
# After restart, verify
docker run --rm alpine free -h
docker run --rm alpine nproc
```

## 📈 Resource Usage Breakdown

### What Uses What in Our Container:

| Component | RAM | Disk | Notes |
|-----------|-----|------|-------|
| **Base Container** | ~500 MB | ~2 GB | Python + OS |
| **Ollama Service** | ~500 MB | ~1 GB | Runtime |
| **CodeLlama 7B** | ~4-6 GB | ~4 GB | Loaded model |
| **Embeddings** | ~500 MB | ~2 GB | Sentence transformers |
| **ChromaDB** | ~200 MB | ~500 MB | Vector database |
| **Working Space** | ~1 GB | ~5 GB | Code, cache, sessions |
| **Total** | **~8 GB** | **~15 GB** | |

### Performance Characteristics:

**With 8GB RAM (Minimum):**
- ✅ Works
- ⚠️ Slow inference (5-10 tokens/sec)
- ⚠️ Might swap to disk
- ❌ Can't run other heavy apps

**With 12GB RAM (Recommended):**
- ✅ Works well
- ✅ Smooth inference (10-20 tokens/sec)
- ✅ Room for development tools
- ✅ Can run browser, VS Code, etc.

**With 16GB RAM (Optimal):**
- ✅ Excellent performance
- ✅ Fast inference (15-30 tokens/sec)
- ✅ Plenty of headroom
- ✅ Can run multiple models

## 🚨 Common Issues & Solutions

### Issue 1: "Out of Memory" Error

**Symptoms:**
- Container crashes
- Ollama fails to load model
- System becomes unresponsive

**Solution:**
```powershell
# Increase Docker memory allocation
# Docker Desktop → Settings → Resources → Memory
# Set to at least 10 GB

# Restart Docker Desktop
```

### Issue 2: Slow Performance

**Symptoms:**
- LLM takes >30 seconds to respond
- File operations are slow
- Container startup is slow

**Solution:**
```powershell
# 1. Increase CPU cores (Docker Settings)
# 2. Use smaller model:
ollama pull codellama:7b-code  # 3.8GB instead of 7GB instruct

# 3. Reduce context window:
# In .env file:
MAX_CONTEXT_TOKENS=2048  # Instead of 4096
```

### Issue 3: Disk Space Issues

**Symptoms:**
- "No space left on device"
- Can't pull models
- Build fails

**Solution:**
```powershell
# Clean up Docker
docker system prune -a --volumes

# Increase disk image size
# Docker Desktop → Settings → Resources → Disk image size
# Set to 60 GB

# Move Docker to another drive if needed
# Docker Desktop → Settings → Resources → Disk image location
```

## 📋 Pre-Flight Checklist

Before starting container:

```powershell
# ========================================
# Pre-Flight Resource Check
# ========================================

# 1. Check Docker is running
docker ps

# 2. Check available resources
docker info | Select-String "CPUs|Memory"

# 3. Check disk space
docker system df

# 4. Clean up if needed
docker system prune -a

# 5. Verify settings meet minimum:
# - RAM: ≥8 GB (12+ recommended)
# - CPU: ≥2 cores (4+ recommended)
# - Disk: ≥20 GB free (30+ recommended)
```

**Expected output:**
```
CPUs: 6
Total Memory: 12 GB
Disk Space Available: 35 GB
```

If values are lower, adjust in Docker Desktop settings!

## 🎯 Recommended Configuration for Your System

Based on typical development setup:

```yaml
Docker Desktop Settings:
  Memory: 12 GB          # Sweet spot for development
  CPUs: 6                # Good balance
  Swap: 4 GB            # For safety
  Disk: 60 GB           # Plenty of room

  Advanced:
    - WSL 2 based engine: ON (Windows)
    - Resource Saver: OFF (keeps Docker ready)
```

## 🚀 Quick Setup Commands

```powershell
# ========================================
# Complete Setup from PowerShell
# ========================================

# 1. Configure Docker Desktop (do this once)
# Manual: Docker Desktop → Settings → Resources
# Set: 12GB RAM, 6 CPUs, 60GB Disk

# 2. Verify configuration
docker run --rm alpine sh -c 'echo "RAM:" && free -h && echo "CPUs:" && nproc'

# 3. Start your container
cd C:\Vijay\Learning\AI\ai-coding-agent
code .
# Click "Reopen in Container"

# 4. Wait for setup (10-15 min first time)
# Downloads: ~5 GB
# Uses RAM: ~8 GB when running
# Uses Disk: ~15 GB total

# 5. Verify inside container
python demo.py
```

## 💾 Optimizations for Limited Resources

If you have <16GB total RAM:

### Option 1: Use Smaller Model
```bash
# Inside container
ollama pull codellama:7b-code       # 3.8 GB vs 7 GB
# or
ollama pull deepseek-coder:1.3b     # 1.3 GB (very small)
```

### Option 2: Reduce Context Window
```bash
# Edit .env
MAX_CONTEXT_TOKENS=2048            # Instead of 4096
WORKING_MEMORY_TOKENS=1000         # Instead of 2000
```

### Option 3: Run Without RAG Initially
```python
# In code, disable RAG for testing
agent = CodingAgent(...)
# Don't call: agent.index_codebase()
# Use: agent.chat(message, use_rag=False)
```

### Option 4: Use Quantized Models
```bash
# Smaller, faster models
ollama pull codellama:7b-code-q4_0  # 4-bit quantized
# 50% smaller, 80% of quality, 2x faster
```

## 📊 Resource Monitoring

**While container is running:**

```powershell
# Windows PowerShell (host)
docker stats

# Shows real-time:
# - Container CPU %
# - Memory usage
# - Network I/O
# - Disk I/O
```

**Inside container:**

```bash
# Check Ollama memory usage
ps aux | grep ollama

# Check overall memory
free -h

# Check disk usage
df -h
```

## ✅ Final Recommendations

**For your setup:**

1. **Configure Docker Desktop:**
   - RAM: 12 GB (if you have 16+ GB total)
   - CPU: 6 cores (if you have 8+ total)
   - Disk: 60 GB

2. **Use mounted workspace** (already configured)
   - No need to copy files
   - Changes sync automatically
   - Still push to git for backup

3. **Monitor first run:**
   - Watch `docker stats`
   - Ensure RAM stays <90%
   - Adjust if needed

4. **Optimize if needed:**
   - Smaller model if slow
   - Reduce context if memory tight
   - Quantized models for speed

**Ready to start?**
```powershell
code .
# Click "Reopen in Container"
```

Your code is already mounted, resources are configured, and you're ready to go! 🚀

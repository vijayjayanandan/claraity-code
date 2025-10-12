# RunPod GPU Deployment Guide

## Why RunPod?

**Problem:** CPU inference with CodeLlama 7B is extremely slow (30-60+ seconds per response)

**Solution:** GPU-accelerated inference on RunPod
- **10-50x faster** inference (1-3 seconds per response)
- **Pay-per-use** pricing (no commitment)
- **Pre-configured GPU images** (CUDA, PyTorch ready)
- **SSH access** for development

---

## Cost Analysis

### Recommended GPU Options

| GPU | VRAM | Performance | Cost/Hour | Best For |
|-----|------|-------------|-----------|----------|
| **RTX 4090** | 24 GB | Excellent | ~$0.69/hr | Development & Testing ⭐ |
| **RTX A5000** | 24 GB | Very Good | ~$0.54/hr | Budget-Conscious |
| **RTX 3090** | 24 GB | Good | ~$0.44/hr | Cost-Effective |
| **RTX A4000** | 16 GB | Good | ~$0.34/hr | Minimal Budget |

**Recommendation:** Start with **RTX 4090** for best experience (~$0.69/hr)

### Cost Estimates

**Development Session (4 hours):**
- RTX 4090: ~$2.76
- RTX 3090: ~$1.76

**Daily Development (8 hours):**
- RTX 4090: ~$5.52
- RTX 3090: ~$3.52

**Monthly (160 hours):**
- RTX 4090: ~$110
- RTX 3090: ~$70

**Note:** RunPod charges **by the minute**, so you only pay when running!

---

## Quick Start Guide

### Prerequisites

1. **RunPod Account**: https://runpod.io (sign up, free account)
2. **Credit Card**: Add payment method (minimum ~$10 credit)
3. **SSH Key**: For secure access

### Step 1: Create SSH Key (If Needed)

**On Windows (PowerShell):**
```powershell
# Generate SSH key
ssh-keygen -t ed25519 -C "your_email@example.com"

# Save to: C:\Users\<username>\.ssh\id_ed25519
# Press Enter for no passphrase (or set one)

# Copy public key
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | clip
```

Your public key is now in clipboard!

### Step 2: Deploy on RunPod

1. **Login to RunPod**: https://www.runpod.io/console/pods

2. **Click "Deploy"** (top right)

3. **Select Template**:
   - Search for "PyTorch"
   - Choose: **"RunPod PyTorch"** (official, CUDA pre-installed)
   - Or: **"RunPod Pytorch 2.1"** (newer)

4. **Select GPU**:
   - Filter: "On-Demand" (for reliability)
   - Choose: **RTX 4090** (or budget alternative)
   - Note: Community Cloud is cheaper but less reliable

5. **Configure Pod**:
   - **Container Disk**: 50 GB (sufficient)
   - **Volume Disk**: 0 GB (not needed for this)
   - **Expose HTTP Ports**: 8888 (Jupyter, optional)
   - **Expose TCP Ports**: 11434 (Ollama API)

6. **Add SSH Key**:
   - Paste your public key from Step 1
   - This enables SSH access

7. **Deploy**: Click "Deploy On-Demand"

### Step 3: Wait for Pod to Start

- Status: "Initializing" → "Running"
- Takes ~30-60 seconds
- You'll see: **SSH Command** and **IP Address**

### Step 4: Connect via SSH

**Copy SSH command from RunPod dashboard**, looks like:
```bash
ssh root@<pod-ip> -p <port> -i ~/.ssh/id_ed25519
```

**On Windows (PowerShell):**
```powershell
# Replace with your actual values from RunPod
ssh root@<pod-ip> -p <port> -i $env:USERPROFILE\.ssh\id_ed25519
```

**First time:** Type "yes" to accept fingerprint

You're now connected to your GPU pod! 🚀

---

## Setup AI Coding Agent on RunPod

Once connected via SSH, run these commands:

### 1. Install System Dependencies

```bash
# Update system
apt-get update && apt-get install -y git curl

# Install Ollama (GPU version automatically detected)
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama service
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 5

# Pull CodeLlama model (GPU accelerated!)
ollama pull codellama:7b-instruct
```

### 2. Clone Your Repository

```bash
# Clone from GitHub
cd /workspace
git clone https://github.com/vijayjayanandan/ai-coding-agent.git
cd ai-coding-agent
```

### 3. Install Python Dependencies

```bash
# Install dependencies
pip install -r requirements.txt

# Install SQLite fix
pip install pysqlite3-binary
```

### 4. Verify GPU Access

```bash
# Check CUDA
nvidia-smi

# Expected output:
# - GPU model (RTX 4090, etc.)
# - Memory: ~24GB total
# - CUDA Version: 12.x or 11.x
```

### 5. Test Ollama with GPU

```bash
# Quick test
ollama run codellama:7b-instruct "Write a hello world function in Python"

# Should respond in 1-3 seconds (vs 30-60s on CPU!)
```

### 6. Run Demo

```bash
# Run the demo
python demo.py

# Should complete in 2-3 minutes (vs 10-20 minutes on CPU!)
```

---

## Speed Comparison

| Task | CPU (Local) | GPU (RunPod RTX 4090) | Speedup |
|------|-------------|----------------------|---------|
| Model Load | 5-10s | 2-3s | 2-3x |
| Simple Query | 30-60s | 1-3s | 20-30x |
| Code Explanation | 60-120s | 3-5s | 20-40x |
| Code Generation | 90-180s | 4-8s | 20-45x |
| Full Demo | 10-20 min | 2-3 min | 5-7x |

**Interactive Development:** Goes from painful to smooth! ⚡

---

## Development Workflow on RunPod

### Option 1: SSH + Local VS Code (Recommended)

**Best for:** Full development experience

1. **Install VS Code Extension**: "Remote - SSH"
2. **Connect**:
   - Open VS Code
   - Press `Ctrl+Shift+P`
   - Select "Remote-SSH: Connect to Host"
   - Enter: `root@<pod-ip> -p <port>`
3. **Open Folder**: `/workspace/ai-coding-agent`
4. **Develop**: Full VS Code experience on GPU pod!

### Option 2: SSH Terminal Only

**Best for:** Quick testing, CLI work

```bash
# Connect via SSH
ssh root@<pod-ip> -p <port>

# Use vim/nano for edits
# Run commands directly
python -m src.cli chat
```

### Option 3: Jupyter Notebook

**Best for:** Experimentation, data analysis

1. **Access**: `http://<pod-ip>:8888` (in browser)
2. **Password**: Check RunPod dashboard for token
3. **Create Notebook**: Test agent interactively

---

## Data Persistence

### Important: Pods are Ephemeral!

**Problem:** When you stop a pod, everything is lost (except volumes)

**Solutions:**

### 1. Use Git (Recommended)

```bash
# Before stopping pod
cd /workspace/ai-coding-agent
git add .
git commit -m "Work in progress"
git push
```

### 2. Use RunPod Network Volume (Optional)

- Create a network volume (persistent storage)
- Attach to pod
- Mount at `/workspace`
- Data survives pod restarts
- **Cost:** ~$0.10/GB/month

### 3. Download Important Files

```bash
# On your Windows machine
scp -P <port> root@<pod-ip>:/workspace/ai-coding-agent/sessions/* ./local-backup/
```

---

## Cost Management Tips

### 1. Stop When Not Using

**Important:** RunPod charges while pod is running!

- **Stop pod** when taking breaks
- **Costs:** $0.00 while stopped
- **Restart:** Takes ~30s, everything reloads

### 2. Use Spot Instances (Advanced)

- **Community Cloud** (spot pricing)
- **50-70% cheaper** than on-demand
- **Risk:** Can be interrupted
- **Best for:** Non-critical testing

### 3. Set Spending Limits

- RunPod Dashboard → Billing
- Set daily/weekly limits
- Get alerts at thresholds

### 4. Monitor Usage

```bash
# Check GPU utilization
watch -n 1 nvidia-smi

# If idle (0% usage), consider stopping
```

---

## Troubleshooting

### Issue: Ollama Not Found

```bash
# Check if installed
which ollama

# If not found, reinstall
curl -fsSL https://ollama.ai/install.sh | sh
```

### Issue: Ollama Service Not Running

```bash
# Check if running
ps aux | grep ollama

# Restart if needed
pkill ollama
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 5
```

### Issue: GPU Not Detected

```bash
# Check CUDA
nvidia-smi

# Check PyTorch CUDA
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"

# If false, template might be CPU-only
# Redeploy with GPU-enabled template
```

### Issue: Out of Memory

```bash
# Check GPU memory
nvidia-smi

# If model too large:
# Use smaller model
ollama pull codellama:7b-code  # Smaller variant

# Or clear cache
ollama rm codellama:7b-instruct
ollama pull codellama:7b-instruct
```

### Issue: Connection Timeout

```bash
# Check pod status in RunPod dashboard
# If "Stopped", restart it
# If "Running", check firewall/ports
```

---

## Advanced: Claude Code CLI on RunPod

You can also install Claude Code CLI on the RunPod pod:

```bash
# Install Node.js (if not present)
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# Install Claude Code CLI
npm install -g @anthropic-ai/claude-code

# Authenticate (will open browser)
claude

# Now you have DUAL GPUs:
# - Local LLM (Ollama/CodeLlama) for agent
# - Claude Max (API) for development assistance
```

---

## Next Steps

1. **Deploy pod** (follow Quick Start above)
2. **Run demo** on GPU (experience the speed!)
3. **Iterate rapidly** (development becomes smooth)
4. **Test real codebases** (index larger projects)
5. **Experiment with models** (try different LLMs)

---

## Alternative: Faster Models

Once on GPU, you can try larger/better models:

```bash
# Try these alternatives:
ollama pull deepseek-coder:6.7b    # Better at code
ollama pull mistral:7b             # Better general performance
ollama pull codellama:13b          # Larger, smarter (needs 16GB+ VRAM)
ollama pull codellama:34b          # Best quality (needs 24GB VRAM)

# Update demo.py to use new model:
# agent = CodingAgent(model_name="deepseek-coder:6.7b", ...)
```

---

## Summary

**Before (CPU):** 30-60s per response, painful development
**After (GPU):** 1-3s per response, smooth experience

**Cost:** ~$0.69/hr (RTX 4090) = ~$5.52 for full day of development

**ROI:** Massive time savings, better learning experience, production-ready performance

---

**Ready to deploy?** Follow the Quick Start Guide above! 🚀

**Questions?** Check Troubleshooting or ask in this session.

---

**Last Updated:** 2025-10-12
**Status:** Ready for deployment

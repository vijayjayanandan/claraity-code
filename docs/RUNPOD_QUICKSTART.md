# RunPod Quick Start - 5 Minute Setup

## TL;DR: Get Running Fast 🚀

**Goal:** AI Coding Agent on GPU pod in 5 minutes

**Cost:** ~$0.69/hour (RTX 4090) = ~$2.76 for 4 hours of development

---

## Step 1: Create SSH Key (1 minute)

**Windows PowerShell:**
```powershell
ssh-keygen -t ed25519 -C "your_email@example.com"
# Press Enter 3 times (default location, no passphrase)

# Copy public key
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | clip
```

✅ Public key is now in your clipboard

---

## Step 2: Deploy Pod (2 minutes)

1. **Login:** https://www.runpod.io/console/pods
2. **Click:** "Deploy" (blue button, top right)
3. **Select Template:** "RunPod PyTorch" (official)
4. **Select GPU:** RTX 4090 (filter by "On-Demand")
5. **Configure:**
   - Container Disk: 50 GB
   - Expose TCP Ports: 11434
   - SSH Public Key: Paste from clipboard
6. **Click:** "Deploy On-Demand"
7. **Wait:** 30-60 seconds for "Running" status

---

## Step 3: Connect & Setup (2 minutes)

**Copy SSH command from RunPod** (looks like):
```bash
ssh root@X.X.X.X -p XXXXX -i ~/.ssh/id_ed25519
```

**Run in PowerShell** (replace with your values):
```powershell
ssh root@<IP> -p <PORT> -i $env:USERPROFILE\.ssh\id_ed25519
```

**Type "yes"** when asked about fingerprint

**Once connected, run ONE command:**
```bash
curl -fsSL https://raw.githubusercontent.com/vijayjayanandan/ai-coding-agent/main/runpod-setup.sh | bash
```

This automated script:
- Installs Ollama with GPU support
- Pulls CodeLlama 7B model
- Clones your repository
- Installs all dependencies
- Verifies everything works

**Takes:** 2-5 minutes (mostly downloading model)

---

## Step 4: Test It! (30 seconds)

```bash
cd /workspace/ai-coding-agent

# Quick test (should respond in 1-3 seconds!)
ollama run codellama:7b-instruct "Write a Python hello world"

# Run demo (should complete in 2-3 minutes vs 10-20 on CPU!)
python demo.py
```

---

## Bonus: Use VS Code Remote (Optional)

**For full IDE experience:**

1. **Install VS Code Extension:** "Remote - SSH"
2. **Connect:**
   - `Ctrl+Shift+P` → "Remote-SSH: Connect to Host"
   - Enter: `root@<IP> -p <PORT>`
3. **Open:** `/workspace/ai-coding-agent`
4. **Code away!** Full VS Code on GPU pod

---

## Speed Comparison

| Task | CPU (Local) | GPU (RunPod) |
|------|-------------|--------------|
| Simple query | 30-60s | 1-3s ⚡ |
| Code explanation | 60-120s | 3-5s ⚡ |
| Full demo | 10-20 min | 2-3 min ⚡ |

**Result:** 10-30x faster responses!

---

## Cost Management

**Remember to STOP pod when not using!**

```bash
# Before logging out
exit  # Close SSH session
```

Then in RunPod dashboard:
- Click "Stop" on your pod
- **Charges stop immediately**
- Restart takes ~30s when needed

**Cost while stopped:** $0.00 ✅

---

## Common Commands

```bash
# Monitor GPU usage
watch -n 1 nvidia-smi

# Check GPU info
nvidia-smi

# Test Ollama
ollama list  # See installed models
ollama ps    # See running models

# Run AI agent
python demo.py                           # Full demo
python -m src.cli chat                   # Interactive
python -m src.cli task "your task here"  # Single task
```

---

## Troubleshooting

**Ollama not responding?**
```bash
pkill ollama
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 5
```

**Model too slow?**
```bash
# Check GPU usage
nvidia-smi
# Should show GPU memory used and compute at 80-100% during inference
```

**Need to update code?**
```bash
cd /workspace/ai-coding-agent
git pull
```

---

## What's Next?

1. ✅ **Running on GPU** - Fast responses
2. **Try different models:**
   ```bash
   ollama pull deepseek-coder:6.7b  # Better at code
   ollama pull mistral:7b            # Better overall
   ollama pull codellama:13b         # Larger (needs 16GB VRAM)
   ```

3. **Index real codebases:**
   ```bash
   # Clone any repository
   git clone https://github.com/user/repo.git

   # Index it
   python -m src.cli index ./repo

   # Ask questions about it!
   python -m src.cli chat
   ```

4. **Experiment with prompts** - Edit `src/prompts/templates.py`

5. **Build features** - Add more tools, improve RAG, etc.

---

## Summary

**Setup Time:** ~5 minutes
**Cost:** ~$0.69/hour
**Performance:** 10-30x faster than CPU
**Result:** Smooth development experience! 🎉

**Full Documentation:** See `RUNPOD_DEPLOYMENT.md` for detailed guide

---

**Ready to deploy?** Follow the 4 steps above! 🚀

**Questions?** Check `RUNPOD_DEPLOYMENT.md` or ask in this session.

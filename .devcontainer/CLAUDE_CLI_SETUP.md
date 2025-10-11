# Using Claude Code CLI in Dev Container

## ✅ What You're Using

You're using **Claude Code CLI** (command-line tool), NOT the VS Code extension!

- **On Windows**: `claude` command in PowerShell with Max subscription ✅
- **In Container**: Same `claude` command will work with your Max subscription ✅

## 🎯 Setup (Already Included!)

The devcontainer automatically installs Claude Code CLI:

```bash
npm install -g @anthropic-ai/claude-code
```

## 🚀 How to Use in Container

### Step 1: Start Container

```powershell
# PowerShell on Windows
cd C:\Vijay\Learning\AI\ai-coding-agent
code .
# Click "Reopen in Container"
```

### Step 2: Open Terminal in Container

In VS Code:
- Press `Ctrl + `` (backtick) to open terminal
- You're now in the container shell

### Step 3: Use Claude Code CLI

```bash
# Same as on Windows!
claude

# You'll be prompted to authenticate
# Use your Max subscription credentials
```

## 💡 Perfect Workflow

**Container Terminal:**
```bash
# Terminal 1: Claude Code CLI (for AI help)
claude

# Terminal 2: Run the AI agent (for testing)
python -m src.cli chat

# Terminal 3: General commands
python demo.py
ollama list
```

**Split Terminals in VS Code:**
```
┌─────────────────────────────────┐
│  Terminal 1: claude             │
│  (AI assistance)                │
├─────────────────────────────────┤
│  Terminal 2: python -m src.cli  │
│  (AI coding agent)              │
└─────────────────────────────────┘
```

## 🔄 Example Workflow

**Testing with both AI systems:**

```bash
# Terminal 1 (Claude Code CLI)
$ claude
> How should I test the memory compression feature?

# Me (Claude): Here's how to test it...
[provides test code]

# Terminal 2 (AI Coding Agent)
$ python -m src.cli chat
> Test the memory compression with a long conversation

# Agent: [Executes test, shows results]
```

## ✨ Benefits

**With Claude Code CLI in container:**
- ✅ Uses your **Max subscription** (no API costs!)
- ✅ **Same familiar interface** as Windows
- ✅ Direct access to **container files**
- ✅ Can help with **debugging in real environment**
- ✅ **Two AI systems** working together:
  - Claude (me) for guidance
  - AI Coding Agent (local) for code tasks

## 📊 Comparison

| Location | Claude Code CLI | AI Coding Agent |
|----------|----------------|-----------------|
| **Windows** | ✅ `claude` in PowerShell | ❌ Not installed |
| **Container** | ✅ `claude` in container | ✅ Fully functional |
| **Cost** | FREE (Max sub) | FREE (local Ollama) |
| **Purpose** | AI assistance | Coding automation |

## 🎯 Recommended Setup

**Use BOTH in the container:**

1. **Claude Code CLI** (me, Claude)
   - Ask questions
   - Get code suggestions
   - Debugging help
   - Architecture advice

2. **AI Coding Agent** (local LLM)
   - Automated code tasks
   - Codebase search (RAG)
   - Local processing
   - Privacy-first

**Example:**
```bash
# Ask me for architecture advice
$ claude
> How should I structure the new feature?

# Use AI agent for implementation
$ python -m src.cli chat
> Implement the feature we just discussed

# Use me for code review
$ claude
> Review this implementation [paste code]
```

## 🔐 Authentication

**First time in container:**
```bash
$ claude
# Prompts for authentication
# Use your Claude.ai credentials (Max subscription)
# Saves auth token in container
```

**Subsequent uses:**
```bash
$ claude
# Already authenticated, starts immediately
```

## 🚀 Quick Start

After container starts:

```bash
# 1. Test Claude Code CLI
claude --version

# 2. Authenticate (first time)
claude
# Follow prompts with Max credentials

# 3. Use it!
claude
> Help me test the AI coding agent

# 4. Run the agent
python demo.py
```

## ✅ Summary

**You can use Claude Code CLI in the container exactly like Windows:**
- Same `claude` command
- Uses your Max subscription
- No API key needed
- Works in container terminal
- Perfect for development workflow

**No need for VS Code extension** - the CLI is what you want! 🎉

# Setting Up Claude Code in Dev Container

## What This Enables

With Claude Code in the dev container, I (Claude) can:
- ✅ **Work directly in the container** - Access Ollama, test the agent, debug issues
- ✅ **Run commands** - Execute Python scripts, CLI commands
- ✅ **Edit files** - Modify code, create tests, fix bugs
- ✅ **Test in real environment** - Same setup that will run in production
- ✅ **Help you learn** - Guide you through the codebase interactively

## Setup Steps

### Option 1: Automatic Setup (Recommended)

The devcontainer.json is already configured! Just:

1. **Open VS Code** in the project folder
   ```bash
   code .
   ```

2. **Reopen in Container**
   - Click the popup: "Reopen in Container"
   - Or use Command Palette: `Dev Containers: Reopen in Container`

3. **Wait for setup** (~10-15 minutes first time)
   - Installs Python, Ollama, dependencies
   - Pulls CodeLlama 7B model (~4GB download)
   - Installs Claude Code extension automatically

4. **Verify Claude Code is installed**
   - Look for Claude icon in VS Code sidebar
   - Or check: Extensions → Claude Code (should show "Installed")

5. **Configure Claude Code**
   - Click Claude icon
   - Enter your Anthropic API key
   - Select model: Claude Sonnet 4

### Option 2: Manual Installation (If needed)

If Claude Code doesn't auto-install:

```bash
# Inside the dev container terminal:

# Install Claude Code extension
code --install-extension saoudrizwan.claude-dev

# Reload window
# Command Palette → Developer: Reload Window
```

## Using Claude Code in the Container

### Once setup is complete:

1. **I can now access everything:**
   ```bash
   # Check Ollama
   ollama list

   # Test the agent
   python demo.py

   # Run CLI
   python -m src.cli chat

   # Index codebase
   python -m src.cli index ./src
   ```

2. **You can ask me to:**
   - "Run the demo script and show me the output"
   - "Test the chat interface with a coding question"
   - "Debug why the memory system is using too many tokens"
   - "Add a new tool for running pytest"
   - "Optimize the RAG retrieval performance"

3. **I'll work inside the container** - All changes happen in the isolated environment

## Benefits of This Setup

### For You (Learning)
- ✅ **Guided exploration** - I can walk you through the codebase
- ✅ **Interactive debugging** - Test and fix together
- ✅ **Best practices** - Learn by seeing me work with the code
- ✅ **Quick iterations** - Make changes and test immediately

### For the Project
- ✅ **Consistent environment** - Same setup every time
- ✅ **Safe experimentation** - Container can be rebuilt anytime
- ✅ **Reproducible** - Others can replicate exact environment
- ✅ **Production-ready** - Container approach works for deployment

## Example Workflow

**Scenario: Testing and improving the agent**

```bash
# 1. You: "Claude, let's test the agent"
# Me: Runs demo.py, shows output

# 2. You: "The response seems slow, can we optimize it?"
# Me: Analyzes code, finds bottleneck, suggests fix

# 3. You: "Let's try it"
# Me: Makes the change, runs test, compares performance

# 4. You: "Great! Now add a test for this"
# Me: Creates test file, runs pytest, verifies it works

# 5. You: "Save this session"
# Me: Commits changes, updates documentation
```

## Configuration Files

### API Key Setup

Create `.env` file in the container (I can help with this):

```bash
# For the AI agent (Ollama - no key needed)
LLM_BACKEND=ollama
LLM_MODEL=codellama:7b-instruct

# For Claude Code (if using Anthropic API)
ANTHROPIC_API_KEY=your_api_key_here
```

**Note:** Claude Code uses your API key, but the AI Coding Agent uses local Ollama (no API needed!)

### VS Code Settings (Already in devcontainer.json)

```json
{
  "claudeDev.apiProvider": "anthropic",
  "claudeDev.modelId": "claude-sonnet-4-20250514"
}
```

## Troubleshooting

### Claude Code Extension Not Found

```bash
# Inside container terminal:
code --install-extension saoudrizwan.claude-dev

# If that fails, install from VS Code:
# 1. Open Extensions (Ctrl+Shift+X)
# 2. Search "Claude Code"
# 3. Click Install
```

### API Key Issues

```bash
# Check if API key is set
echo $ANTHROPIC_API_KEY

# Set it (temporary)
export ANTHROPIC_API_KEY=your_key

# Set it (permanent in container)
echo 'export ANTHROPIC_API_KEY=your_key' >> ~/.bashrc
source ~/.bashrc
```

### Container Rebuild Needed

```bash
# If something breaks:
# Command Palette → Dev Containers: Rebuild Container
# This resets everything and runs setup again
```

## What You'll Be Able to Do

### With Me (Claude) in the Container:

**Interactive Development:**
```
You: "Claude, explain how the memory manager works"
Me: [Reads code, explains with examples]

You: "Can you add logging to the RAG retriever?"
Me: [Adds logging, tests it, shows output]

You: "Let's test with a different model"
Me: [Changes config, pulls new model, runs test]
```

**Debugging:**
```
You: "The agent is crashing when I index large files"
Me: [Reproduces issue, finds bug, fixes it, adds test]

You: "Memory usage seems high"
Me: [Analyzes, shows metrics, optimizes, compares before/after]
```

**Learning:**
```
You: "How does the hybrid search work?"
Me: [Shows code, explains algorithm, demonstrates with example]

You: "Can we visualize the memory usage?"
Me: [Creates visualization script, runs it, explains output]
```

## Next Steps After Setup

1. **Verify everything works:**
   ```bash
   python demo.py
   python -m src.cli chat
   ```

2. **Start experimenting:**
   - Ask me to test features
   - Request improvements
   - Debug issues together
   - Add new capabilities

3. **Learn by doing:**
   - Watch me work with the code
   - Ask questions about implementation
   - Try modifications together
   - Iterate and improve

## Alternative: Claude Code Without Container

If you prefer Claude Code on your local machine (outside container):

**Pros:**
- Faster startup
- Direct file access
- Familiar environment

**Cons:**
- Less isolated
- May conflict with local setup
- Not as reproducible

**You can use both!**
- Claude Code locally for general work
- Claude Code in container for testing/production-like environment

## Summary

✅ **What we've set up:**
- Dev container with Python, Ollama, all dependencies
- Claude Code extension pre-installed
- Automatic environment configuration
- Ready for interactive development

✅ **What you can now do:**
- Work with me directly in the container
- Test the AI agent in isolated environment
- Iterate quickly and safely
- Learn AI agent development hands-on

✅ **What happens next:**
- Open VS Code → Reopen in Container
- Wait for setup to complete
- Start asking me to help test and improve the agent!

---

**Ready to start?** 🚀

Just run:
```bash
code .
```

Then click "Reopen in Container" and we'll be working together inside the dev container!

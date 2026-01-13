# AI Coding Agent

An advanced AI coding agent optimized for small open-source LLMs, featuring state-of-the-art memory management, RAG-powered code understanding, and intelligent prompt engineering. Designed for organizations with strict data residency requirements that need self-hosted AI solutions.

**🚀 GPU-Accelerated | 🔒 Privacy-First | 🎯 Production-Ready**

## ✨ Key Features

### Core Capabilities
- **Intelligent Workflow Orchestration**: Plan-Execute-Verify system that automatically decides when to use structured workflows vs direct execution
- **Multi-Layered Memory System**: Hierarchical memory architecture (working, episodic, semantic) to overcome context window limitations
- **File-Based Hierarchical Memory**: Team-shareable, version-controlled memory system with 4-level hierarchy (enterprise → user → project → imports) for persistent coding standards and preferences
- **RAG-Powered Code Understanding**: Hybrid search combining semantic and keyword-based retrieval with AST-based code parsing
- **Advanced Context Management**: Dynamic context assembly with intelligent prioritization and compression
- **Optimized Prompt Engineering**: Task-specific templates with few-shot examples and chain-of-thought reasoning
- **Multi-LLM Backend Support**: Compatible with OpenAI, Alibaba Cloud, Ollama, and any OpenAI-compatible API
- **Privacy-First Design**: Complete local execution option with zero external data transmission

### Workflow Features (NEW!)
- **Task Analysis**: Automatically classifies tasks (9 types, 5 complexity levels) and estimates resource requirements
- **Intelligent Planning**: LLM-powered execution plan generation with dependency validation
- **Step-by-Step Execution**: Direct tool execution with real-time progress tracking and error recovery
- **Decision Logic**: Smart routing between workflow and direct execution based on task type and complexity
- **User Approval Gates**: Interactive approval for high-risk operations with detailed risk assessment
- **Progress Transparency**: Real-time callbacks showing what the agent is doing at each step

### Advanced Features
- **AST-Based Code Analysis**: Deep understanding of code structure using Tree-sitter parsers for 10+ languages
- **Incremental Codebase Learning**: Progressive understanding without overwhelming small context windows
- **Token Budget Management**: Dynamic allocation of context budget based on task requirements
- **Session Persistence**: Save and restore conversation state across sessions
- **Checkpoints for Long-Running Projects**: Create save points during multi-day development with full context preservation
- **Tool Execution Engine**: Read, write, edit, search, and analyze code intelligently

### Language Support
- **Python** ✅ (fully tested)
- **Java / Spring Boot** ✅ (parser verified)
- **TypeScript / React / TSX** ✅ (parser verified)
- Plus: JavaScript, Go, Rust, C/C++, C#, Ruby, PHP

## 🏗️ Architecture

The agent uses a sophisticated multi-component architecture:

```
┌─────────────────────────────────────────────────────────┐
│                    Coding Agent                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │   Memory    │  │     RAG     │  │   Prompts   │    │
│  │  Manager    │  │   System    │  │  Optimizer  │    │
│  └─────────────┘  └─────────────┘  └─────────────┘    │
│         │                │                 │            │
│         └────────────────┴─────────────────┘            │
│                          │                               │
│                  ┌───────▼────────┐                     │
│                  │  LLM Backend   │                     │
│                  │ (Ollama/vLLM)  │                     │
│                  └────────────────┘                     │
└─────────────────────────────────────────────────────────┘
```

**See [ARCHITECTURE.md](ARCHITECTURE.md)** for detailed system design.

## 🚀 Quick Start

### Prerequisites
- Python 3.10+ (3.11 recommended)
- 8GB+ RAM (16GB+ recommended)
- GPU optional but highly recommended (10-30x performance improvement)
- Local LLM backend (Ollama recommended)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/vijayjayanandan/ai-coding-agent.git
cd ai-coding-agent
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env with your configuration
```

### Setting Up LLM Backend

#### Option 1: Ollama (Recommended)
```bash
# Install Ollama from https://ollama.ai
# Pull a code-optimized model
ollama pull deepseek-coder:6.7b-instruct
# Or try: codellama:7b-instruct, qwen2.5-coder:7b
```

#### Option 2: GPU-Accelerated with RunPod (Production)
For 10-30x faster performance, deploy on RunPod with GPU:

```bash
# See RUNPOD_QUICKSTART.md for detailed setup
# Quick summary:
# 1. Create RunPod account + SSH key
# 2. Deploy RTX 4090 pod (~$0.69/hour)
# 3. Run automated setup script
# 4. Get 1-3 second responses instead of 30-60 seconds!
```

**Performance Comparison:**
- CPU (local): 30-60 seconds per query
- GPU (RunPod RTX 4090): 1-5 seconds per query

See [RUNPOD_QUICKSTART.md](RUNPOD_QUICKSTART.md) for step-by-step GPU deployment.

### Usage

#### Command Line Interface

```bash
# Interactive chat mode
python -m src.cli chat

# Execute a single task
python -m src.cli task "Explain the memory system" --type explain

# Index a codebase
python -m src.cli index ./src

# Run demo
python demo.py

# Run capability tests
python test_agent_capabilities.py
```

**Memory Management Commands (in chat mode):**
```bash
# Show current file-based memories
> memory

# Initialize project memory template
> memory-init

# Quick add a memory (e.g., coding standard)
> memory-add "Always use 2-space indentation"

# Reload memories after editing the file
> memory-reload
```

**File-Based Memory Hierarchy:**
- **Enterprise** (`/etc/opencodeagent/memory.md` or `C:/ProgramData/opencodeagent/`): Organization-wide policies
- **User** (`~/.opencodeagent/memory.md`): Personal preferences across all projects
- **Project** (`./.opencodeagent/memory.md`): Project-specific standards (version controlled)
- **Imports** (`@path/to/file.md`): Modular memory files with circular detection

**Session Persistence Commands (in chat mode):**
```bash
# Save current session with metadata
> session-save
Session name: feature-auth
Task description: Implementing JWT authentication
Tags: feature,auth,backend

# List all saved sessions
> sessions
╭─ Saved Sessions (5 total) ───────────────────────────╮
│ ID       │ Name        │ Description    │ Msgs │ ... │
├──────────┼─────────────┼────────────────┼──────┼─────┤
│ abc12345 │ feature-auth│ JWT auth...    │ 42   │ 2h  │
╰───────────────────────────────────────────────────────╯

# Load a saved session (by ID, short ID, or name)
> session-load abc12345
✓ Session loaded! 42 messages restored

# Show detailed session info
> session-info feature-auth

# Delete old sessions
> session-delete old-test-session
```

**Session Persistence Features:**
- **Complete State Preservation**: Saves all messages, task context, episodic memory, and file memories
- **Fast Session Listing**: Instant listing even with 100+ sessions using manifest-based indexing
- **Flexible Loading**: Load by full UUID, 8-char short ID, or human-readable name
- **Tag-Based Organization**: Organize sessions with tags (e.g., `feature`, `bugfix`, `auth`)
- **Interactive Prompts**: User-friendly CLI guides you through save process
- **Safe Operations**: Confirmation prompts prevent accidental data loss

**Common Use Cases:**
- Pause work on a feature and resume later with full context
- Save before switching between multiple projects
- Archive completed sessions for future reference
- Share session IDs with team members for collaboration
- Organize work by tags (project, feature type, etc.)

**Session Storage:**
Sessions are stored in `.opencodeagent/sessions/` with the following structure:
```
.opencodeagent/
  sessions/
    manifest.json              # Fast index for listing
    <uuid>/
      metadata.json            # Session info (name, tags, timestamps)
      working_memory.json      # All messages and context
      episodic_memory.json     # Conversation history
      task_context.json        # Current task details
      file_memories.txt        # Loaded CLAUDE.md content
```

### Checkpoints for Long-Running Projects

**Checkpoints** are work-in-progress snapshots designed for multi-day/multi-session development. Unlike session persistence (which saves complete conversations), checkpoints create save points you can return to later.

**Think of it like save games:** Resume development exactly where you left off, with full context of architecture decisions, pending tasks, and conversation history.

**CLI Commands (in chat mode):**
```bash
# Create a checkpoint during development
> checkpoint-save
Description: Backend API complete, frontend pending
Phase: Phase 1 - API Development
Pending tasks:
  - Create React dashboard
  - Add authentication UI
  - Implement real-time updates
✓ Checkpoint created: abc12345

# List all checkpoints for current project
> checkpoints
╭─ Project Checkpoints (3 total) ──────────────────────╮
│ ID       │ Description        │ Files │ Phase      │
├──────────┼────────────────────┼───────┼────────────┤
│ abc12345 │ Backend API comp...│ 12    │ Phase 1    │
│ def67890 │ User auth added    │ 15    │ Phase 2    │
╰───────────────────────────────────────────────────────╯

# Restore from a checkpoint (rollback)
> checkpoint-restore abc12345
✓ Restored to: Backend API complete, frontend pending
✓ Restored 24 messages, 8 tool calls
✓ Working directory: ./my-project
✓ Pending tasks: 3

# Delete all checkpoints (WARNING: irreversible!)
> checkpoint-clear-all
⚠ Delete ALL checkpoints? (yes/no): yes
✓ Deleted 3 checkpoint(s)
```

**Python API (for automation/testing):**
```python
from src.orchestration import AgentOrchestrator

# Start a multi-session project
orchestrator = AgentOrchestrator(
    working_directory="./music-academy"
)
session = orchestrator.start_conversation(
    task_description="Build online music learning academy"
)

# === Day 1: Build backend ===
session.send_message("Create database models for User, Course, Lesson")
session.send_message("Create FastAPI endpoints for course catalog")

# Create checkpoint before ending day
checkpoint_id = session.save_checkpoint(
    description="Backend foundation complete",
    phase="Phase 1 - Backend",
    pending_tasks=[
        "Create React frontend",
        "Add authentication",
        "Implement video player"
    ]
)
print(f"Checkpoint saved: {checkpoint_id}")

# End day 1
orchestrator.end_conversation(session.conversation_id)

# === Day 2: Resume work ===
# Start fresh session (simulates new day/terminal)
new_session = orchestrator.start_conversation(
    task_description="Continue music academy"
)

# Restore checkpoint
new_session.restore_checkpoint(checkpoint_id)
# Agent now has full context from day 1!

# Continue building
new_session.send_message("Create the React student dashboard")
```

**Checkpoint Features:**
- **Full Context Preservation**: Saves conversation history, files created, tool calls, and pending tasks
- **Cross-Session Resume**: Start new terminal/session and pick up exactly where you left off
- **Architecture Memory**: Agent remembers database schemas, API endpoints, and design decisions
- **Pending Task Tracking**: Checkpoint stores what's left to do (frontend, tests, deployment, etc.)
- **Project-Scoped**: Checkpoints stored in `.checkpoints/` directory within project workspace
- **Automatic Cleanup**: Configure `max_checkpoints` to auto-delete old checkpoints

**Common Use Cases:**
- **Multi-day development**: Build complex apps over several days with full context
- **Experiment safety**: Create checkpoint before trying risky changes, restore if needed
- **Team handoffs**: Share checkpoint ID so teammates can resume your work
- **Milestone tracking**: Save checkpoints after completing each project phase
- **Testing/QA**: Restore to specific states for bug reproduction

**Checkpoint vs Session Persistence:**
| Feature | Checkpoints | Session Persistence |
|---------|-------------|---------------------|
| **Purpose** | Work-in-progress snapshots | Complete conversation archives |
| **Scope** | Project-specific | Global across all projects |
| **Use Case** | Resume multi-day development | Pause/resume conversations |
| **Storage** | `.checkpoints/` in project | `.opencodeagent/sessions/` |
| **Restore Behavior** | Rolls back to checkpoint state | Loads full conversation |
| **Pending Tasks** | Yes, explicitly tracked | No, use tags instead |

**Checkpoint Storage:**
Checkpoints are stored in your project's `.checkpoints/` directory:
```
my-project/
  .checkpoints/
    checkpoint_abc12345.json   # Includes working memory, tool history, pending tasks
    checkpoint_def67890.json
```

Each checkpoint contains:
- **Conversation history**: All messages exchanged with agent
- **Tool execution history**: Files created/modified, commands run
- **Task context**: Current phase, pending tasks, file count
- **Metadata**: Timestamp, description, working directory

#### Python API

**Basic Usage:**
```python
from src.core import CodingAgent

# Initialize agent with OpenAI-compatible API (Alibaba Cloud example)
agent = CodingAgent(
    backend="openai",
    model_name="qwen3-coder-plus",
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    api_key_env="DASHSCOPE_API_KEY",
    context_window=32768,
)

# Or use local Ollama for complete data residency
agent = CodingAgent(
    backend="ollama",
    model_name="deepseek-coder:6.7b-instruct",
    context_window=16384,
)

# Index your codebase
stats = agent.index_codebase(directory="./src")
print(f"Indexed {stats['total_files']} files")

# Execute a task - agent automatically decides workflow vs direct
response = agent.execute_task(
    task_description="Explain how the RAG system works",
    task_type="explain",
    use_rag=True,
)
print(response.content)

# Interactive chat
response = agent.chat("What is the MemoryManager class?")
print(response)
```

**Workflow Features (Advanced):**
```python
# Implementation tasks automatically use workflow (analyze → plan → execute)
response = agent.execute_task(
    task_description="Add a new tool for running shell commands",
    task_type="implement",
)
# Output:
# 📊 TASK ANALYSIS
# Task Type: feature
# Complexity: MODERATE
# Risk Level: MEDIUM
# ... (detailed analysis)
#
# 📋 EXECUTION PLAN
# Step 1: Read existing tool implementations
# Step 2: Design new RunCommandTool class
# Step 3: Implement the tool
# ...
#
# ▶️  Step 1: starting...
# ✅ Step 1: completed
# ... (real-time progress)

# Explanation queries use fast direct execution
response = agent.execute_task(
    task_description="How does the workflow system work?",
    task_type="explain",
)
# → Fast response, no planning overhead

# Force specific execution mode if needed
response = agent.execute_task(
    task_description="Some task",
    force_workflow=True,  # Always use workflow
    # force_direct=True,   # Always use direct
)

# Check execution mode in response metadata
print(response.metadata["execution_mode"])  # "workflow" or "direct"
```

**Session Persistence (Python API):**
```python
# Interactive work session
agent.chat("Implement JWT authentication")
agent.chat("Add login endpoint")
agent.chat("Add password hashing")

# Save session with metadata
session_id = agent.memory.save_session(
    session_name="jwt-auth-feature",
    task_description="Implementing JWT authentication for REST API",
    tags=["feature", "auth", "backend"],
)
print(f"Session saved: {session_id[:8]}")  # abc12345

# Later - create new agent and load session
new_agent = CodingAgent(backend="openai", model_name="qwen3-coder-plus")
new_agent.memory.load_session("abc12345")  # Load by short ID
# Or: new_agent.memory.load_session("jwt-auth-feature")  # Load by name

# Continue from where you left off with full context
new_agent.chat("Now add token refresh logic")

# List all saved sessions programmatically
from src.core.session_manager import SessionManager
session_mgr = SessionManager()
sessions = session_mgr.list_sessions()
for session in sessions:
    print(f"{session.short_id}: {session.name} ({session.message_count} messages)")

# Filter sessions by tags
auth_sessions = session_mgr.list_sessions(tags=["auth"])

# Get detailed session info
metadata = session_mgr.get_session_metadata("abc12345")
print(f"Created: {metadata.created_at}")
print(f"Duration: {metadata.duration_minutes} minutes")
print(f"Tags: {', '.join(metadata.tags)}")

# Delete old sessions
session_mgr.delete_session("old-test-id")
```

## 📊 Performance & Testing

### Verified Capabilities ✅
- **RAG System**: 242 intelligent chunks from 28 files with AST-based parsing
- **Memory Management**: Multi-turn conversations with full context retention
- **Code Understanding**: Deep comprehension of complex architectures
- **Fast Inference**: 1-5 second responses with GPU acceleration

### Test Results (RunPod RTX 4090)
```
Response Times:
├─ Simple Query: 1.5s
├─ Code Generation: 1.5s
├─ Complex Explanation: 3-5s
└─ RAG Retrieval + Response: 4-6s

GPU Utilization:
├─ GPU Usage: 96% during inference
├─ Memory Bandwidth: 88%
└─ VRAM: 6.5GB / 24GB
```

**See [RUNPOD_TEST_RESULTS.md](RUNPOD_TEST_RESULTS.md)** for complete test report.

## 📁 Project Structure

```
ai-coding-agent/
├── src/
│   ├── core/              # Agent orchestration & context building
│   ├── memory/            # Hierarchical memory system
│   ├── rag/               # RAG system with AST parsing
│   ├── prompts/           # Prompt templates & optimization
│   ├── llm/               # LLM backend integrations
│   ├── tools/             # Tool execution engine
│   └── cli.py             # Command-line interface
├── demo.py                # Demo script
├── test_agent_capabilities.py  # Comprehensive tests
├── requirements.txt       # Python dependencies
└── Documentation/
    ├── ARCHITECTURE.md    # System design
    ├── GETTING_STARTED.md # Detailed setup guide
    ├── RUNPOD_QUICKSTART.md  # GPU deployment
    └── RUNPOD_TEST_RESULTS.md # Test results
```

## 🔧 Configuration

### Environment Variables
```bash
# LLM Backend
OLLAMA_URL=http://localhost:11434
MODEL_NAME=deepseek-coder:6.7b-instruct

# Memory Configuration
MAX_WORKING_MEMORY_TOKENS=2048
MAX_EPISODIC_MEMORY_TOKENS=10240

# RAG Configuration
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
CHUNK_SIZE=512
CHUNK_OVERLAP=50
```

### Supported Models
- **DeepSeek Coder** (6.7B, 33B) - Excellent for code understanding
- **CodeLlama** (7B, 13B, 34B) - General code generation
- **Qwen2.5-Coder** (7B, 14B, 32B) - Strong code intelligence
- **StarCoder2** (7B, 15B) - Code-specific training
- Any Ollama-compatible model

## 🎯 Use Cases

### Validated Use Cases
1. **Intelligent Code Implementation**: Plan-execute-verify workflow for feature development
2. **Code Explanation**: Understand complex architectures and patterns
3. **Bug Fixing**: Systematic debugging with step-by-step execution
4. **Code Refactoring**: Safe refactoring with dependency analysis
5. **Code Search**: Find relevant code using natural language queries
6. **Conversational Coding**: Multi-turn context-aware dialogue
7. **Knowledge Retrieval**: RAG-powered code knowledge base

### Example Workflows

**Scenario 1: Feature Implementation (Uses Workflow)**
```
User: "Add a new tool for listing directories"

Agent:
1. 📊 Analyzes: feature, moderate complexity, 3 files, 5 iterations
2. 📋 Creates Plan:
   - Read existing tools
   - Design new tool class
   - Implement with error handling
   - Write tests
   - Integrate with agent
3. ⚙️  Executes: Step-by-step with real-time progress
4. ✅ Verifies: All steps completed successfully
```

**Scenario 2: Code Explanation (Uses Direct)**
```
User: "Explain how the memory system works"

Agent:
→ Fast direct execution (2-5 seconds)
→ Uses RAG to retrieve relevant code
→ Provides detailed explanation
```

**Scenario 3: Complex Refactoring (Uses Workflow + Approval)**
```
User: "Refactor the entire memory system to use Redis"

Agent:
1. 📊 Analyzes: refactor, very complex, HIGH RISK
2. 📋 Creates Plan: 12 steps with rollback strategy
3. ⏸️  Asks for Approval: Shows risk assessment
4. ⚙️  Executes: Only after user confirmation
```

### Ideal For
- Organizations with data residency requirements
- Teams needing self-hosted AI solutions
- Privacy-sensitive development environments
- Regulated industries (finance, healthcare, government)
- Developers who want transparent, explainable AI assistance

## 🛠️ Development

### Running Tests
```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run comprehensive tests
python test_agent_capabilities.py

# Run demo
python demo.py
```

### Key Dependencies
- `transformers>=4.40.0` - HuggingFace models
- `sentence-transformers>=2.7.0` - Embeddings
- `chromadb>=0.4.24` - Vector database
- `tree-sitter==0.21.3` - AST parsing (specific version required)
- `tree-sitter-languages>=1.10.2` - Language parsers
- `pysqlite3-binary` - SQLite upgrade for ChromaDB
- `rich>=13.7.0` - Beautiful CLI output

## 🤝 Contributing

Contributions are welcome! Areas for improvement:
- Additional language parsers (JSX, Vue, etc.)
- More LLM backend integrations
- Enhanced tool system
- Web UI (FastAPI + React)
- Multi-agent coordination

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

Built with:
- [Ollama](https://ollama.ai/) - Local LLM runtime
- [ChromaDB](https://www.trychroma.com/) - Vector database
- [Tree-sitter](https://tree-sitter.github.io/) - AST parsing
- [Sentence Transformers](https://www.sbert.net/) - Embeddings
- [Rich](https://rich.readthedocs.io/) - Beautiful terminal output

## 📚 Documentation

### 🌟 Start Here (For Developers & AI Assistants)

**Essential Reading:**
1. **[CODEBASE_CONTEXT.md](CODEBASE_CONTEXT.md)** ⭐ - **Master project documentation**
   - Complete codebase overview (85+ files)
   - Architecture decisions and rationale
   - File-by-file breakdown with purpose and key concepts
   - Common development patterns
   - Known issues and technical debt
   - **Purpose:** Get full project context in < 2 minutes

2. **[README.md](README.md)** (this file) - User-facing documentation
   - Quick start guide
   - Usage examples
   - Feature overview

3. **[CLAUDE.md](CLAUDE.md)** - Session handoff for AI assistants
   - Current task status
   - Recent changes (last session only)
   - Immediate next steps
   - **Purpose:** Quick session continuation

### Core System Documentation

**Setup & Deployment:**
- [GETTING_STARTED.md](GETTING_STARTED.md) - Detailed setup guide
- [RUNPOD_QUICKSTART.md](RUNPOD_QUICKSTART.md) - GPU deployment (5 minutes)
- [RUNPOD_DEPLOYMENT.md](RUNPOD_DEPLOYMENT.md) - Comprehensive GPU guide
- [RUNPOD_TEST_RESULTS.md](RUNPOD_TEST_RESULTS.md) - Performance benchmarks

**Architecture & Design:**
- [ARCHITECTURE.md](ARCHITECTURE.md) - Original system design
- [WORKFLOW_ARCHITECTURE.md](WORKFLOW_ARCHITECTURE.md) - Workflow system design (1,100+ lines)

### Workflow System Implementation (Week 1-2)

**Summaries:**
- [WORKFLOW_WEEK1_COMPLETE.md](WORKFLOW_WEEK1_COMPLETE.md) - Week 1 complete (400 lines)
- [WORKFLOW_WEEK2_DAY1_COMPLETE.md](WORKFLOW_WEEK2_DAY1_COMPLETE.md) - Bug fixes (29/29 tests passing!)

**Daily Implementation Details:**
- [WORKFLOW_DAY1_COMPLETE.md](WORKFLOW_DAY1_COMPLETE.md) - TaskAnalyzer implementation
- [WORKFLOW_DAY3-4_COMPLETE.md](WORKFLOW_DAY3-4_COMPLETE.md) - TaskPlanner implementation
- [WORKFLOW_DAY5_COMPLETE.md](WORKFLOW_DAY5_COMPLETE.md) - ExecutionEngine implementation
- [WORKFLOW_DAY6_COMPLETE.md](WORKFLOW_DAY6_COMPLETE.md) - Integration with CodingAgent

### Documentation Navigation Guide

**I'm a new developer, where do I start?**
→ Read [CODEBASE_CONTEXT.md](CODEBASE_CONTEXT.md) for complete project understanding, then [GETTING_STARTED.md](GETTING_STARTED.md) for setup

**I'm an AI assistant joining a session:**
→ Read [CODEBASE_CONTEXT.md](CODEBASE_CONTEXT.md) first (< 2 min), then [CLAUDE.md](CLAUDE.md) for current status

**I want to understand the workflow system:**
→ [WORKFLOW_ARCHITECTURE.md](WORKFLOW_ARCHITECTURE.md) for design, [WORKFLOW_WEEK1_COMPLETE.md](WORKFLOW_WEEK1_COMPLETE.md) for implementation summary

**I need to deploy on GPU:**
→ [RUNPOD_QUICKSTART.md](RUNPOD_QUICKSTART.md) for fast setup

**I want to understand a specific file:**
→ [CODEBASE_CONTEXT.md](CODEBASE_CONTEXT.md) has file-by-file breakdown with purpose and key concepts

## 🚀 What's Next?

**Workflow System - Week 1 Complete (✅ DONE):**
- [x] Intelligent workflow orchestration (2,000+ lines)
- [x] Task analysis and planning system
- [x] Step-by-step execution engine
- [x] Comprehensive testing (75+ tests)

**Workflow System - Week 2 Days 1-7 Complete (✅ DONE):**
- [x] Fixed callback signature mismatch (4 tests)
- [x] Fixed response generation data type issues
- [x] Fixed WorkingMemory len() access (2 tests)
- [x] All 29 integration tests passing ✅
- [x] Essential tools integrated (10 production tools)
- [x] Three-tier verification layer (always works, tool-enhanced, git-based)
- [x] E2E testing (8 comprehensive scenarios, 143/143 tests passing)

**Claude Code Integration - Phase 1 (In Progress):**
- [x] **File-Based Hierarchical Memory** (✅ COMPLETE)
  - 4-level hierarchy (enterprise → user → project → imports)
  - CLI commands (memory, memory-init, memory-add, memory-reload)
  - Auto-loading on agent initialization
  - 61 tests passing, 89% coverage on file_loader
- [ ] Permission Modes (Plan/Normal/Auto) - Week 1 remaining days
- [ ] Enhanced Prompts Integration - Week 2

**Near-Term Roadmap:**
- [ ] Automated Rollback System (Week 3: FileStateTracker + RollbackEngine)
- [ ] Multiple Tool Calls (Week 4: Parallel execution + batch operations)

**Future Enhancements:**
- [ ] Web UI (FastAPI + React)
- [ ] Multi-agent system
- [ ] Code execution sandbox
- [ ] Plugin system
- [ ] More language support (JSX, Vue, Kotlin, Swift)

---

**⭐ Star this repo if you find it useful!**

**💬 Questions?** Open an issue or discussion.

**📧 Contact:** [vijayjayanandan](https://github.com/vijayjayanandan)

**Made with ❤️ for the AI & open-source community**

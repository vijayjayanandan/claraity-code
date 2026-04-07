/**
 * TracePanel — Animated cartoon visualization of the ClarAIty agent pipeline.
 * POC: hardcoded mock trace, auto-play, expandable detail panel.
 */
import { useState, useLayoutEffect, useRef, useCallback, useEffect } from "react";

// ─── Types ─────────────────────────────────────────────────────────────────────

type NodeId = "user" | "agent" | "llm" | "tools" | "store" | "context_builder" | "gating";
type StepType = "request" | "llm_call" | "llm_response" | "tool_execute" | "tool_result" | "persist" | "context_assembly" | "context_source" | "gate_check" | "approval" | "subagent_start" | "subagent_end";
type SceneState = "main" | "sub";

interface TraceStep {
  id: number;
  from: NodeId;
  to: NodeId;
  label: string;
  type: StepType;
  data: string;
  durationMs: number;
  /** For llm_call: { "System Prompt", "Messages", "Tools" }. For llm_response: { "Thinking", "Response" } */
  sections?: Record<string, string>;
  /** LLM reasoning block — shown in thinking cloud above LLM character */
  thinking?: string;
}

interface NodeDef {
  id: NodeId;
  x: number;
  y: number;
  label: string;
  color: string;
}

/** Loose step shape from .trace.jsonl — `from`/`to` are strings, not NodeId. */
interface ExternalTraceStep {
  id: number;
  from: string;
  to: string;
  label: string;
  type: string;
  data: string;
  durationMs: number;
  sections?: Record<string, string>;
  thinking?: string;
}

interface TracePanelProps {
  onBack: () => void;
  /** Real trace steps from .trace.jsonl — falls back to MOCK_STEPS if null/empty */
  steps?: ExternalTraceStep[] | null;
  /** Whether trace capture is enabled (from config.yaml) */
  traceEnabled?: boolean;
  /** Toggle trace capture on/off */
  onToggleTrace?: (enabled: boolean) => void;
  /** Clear trace data (with confirmation) */
  onClearTrace?: () => void;
}

// ─── SVG Layout ────────────────────────────────────────────────────────────────

const VW = 960;
const VH = 540;
const VY0 = -30;  // viewBox y-origin (negative = headroom for thinking cloud)

const NODES: Record<NodeId, NodeDef> = {
  store:           { id: "store",           x: 300, y: 80,   label: "Store",           color: "#EF9A9A" },
  context_builder: { id: "context_builder", x: 560, y: 80,   label: "Context Builder", color: "#FFB300" },
  user:            { id: "user",            x: 110, y: 250,  label: "User",            color: "#FF8A65" },
  agent:           { id: "agent",           x: 480, y: 250,  label: "Agent",           color: "#42A5F5" },
  llm:             { id: "llm",             x: 840, y: 250,  label: "LLM",             color: "#CE93D8" },
  gating:          { id: "gating",          x: 300, y: 420,  label: "Tool Gating",     color: "#F06292" },
  tools:           { id: "tools",           x: 560, y: 420,  label: "Tools",           color: "#4DB6AC" },
};

// ─── Mock Trace Data ────────────────────────────────────────────────────────────

const MOCK_STEPS: TraceStep[] = [
  {
    id: 1, from: "user", to: "agent",
    label: "Request received",
    type: "request",
    durationMs: 1400,
    data: `User message (from VS Code extension):

"Can you edit the multiply function in utils.py to multiply by 3 instead of 2?"`,
  },
  // ── Steps 2-7: Context Assembly — 5 sources + store fetch ──
  { id: 2, from: "context_builder", to: "context_builder",
    label: "System Prompt: loaded", type: "context_source", durationMs: 700,
    data: `Base system prompt loaded (2,400 tokens).\n\nIncludes: role definition, tool usage rules, safety constraints, output format.`,
    sections: { "System Prompt": "You are ClarAIty, an expert AI coding assistant running inside VS Code.\nBe concise, precise, and always prefer targeted edits over full rewrites.\nNever guess at file contents -- read first, then edit.\n\n# Tools\nYou have access to: read_file, write_file, edit_file, list_dir, run_command.\nAlways read before editing. Use edit_file for targeted changes.\n\n# Safety\nNever execute destructive commands without confirmation.\nDo not modify files outside the workspace." } },
  { id: 3, from: "context_builder", to: "context_builder",
    label: "CLARAITY.md: loaded", type: "context_source", durationMs: 600,
    data: `Project instructions loaded from CLARAITY.md (340 lines).`,
    sections: { "CLARAITY.md": "# ClarAIty AI Coding Agent\n\n## Quick Start\npython -m src.cli\n\n## Key Abstractions\n- CodingAgent: Main facade\n- MemoryManager: Single writer for persistence\n- MessageStore: In-memory + JSONL\n\n## Hard Constraints\n1. Use get_logger(), not logging.getLogger()\n2. No emojis in Python (cp1252)\n3. StoreAdapter is READ-ONLY" } },
  { id: 4, from: "context_builder", to: "context_builder",
    label: "Knowledge DB: loaded", type: "context_source", durationMs: 600,
    data: `Architecture brief loaded from claraity_knowledge.db (SQLite).`,
    sections: { "Knowledge DB": "# Architecture Brief\n\n## Modules: 15\nmod-core (agent.py, tool_gating.py, stream_phases.py)\nmod-memory (memory_manager.py, working_memory.py)\nmod-session (memory_store.py, hydrator.py)\nmod-ui (app.py, store_adapter.py)\nmod-tools (file_operations.py, tool_schemas.py)\nmod-llm (openai_backend.py, anthropic_backend.py)\n\n## Key Decisions\n- MessageStore is projection, JSONL is ledger\n- Single async path via stream_response()\n- MemoryManager is sole writer" } },
  { id: 5, from: "context_builder", to: "context_builder",
    label: "Memory Files: loaded", type: "context_source", durationMs: 500,
    data: `Loaded from .claraity/memory.md hierarchy (project + user level).`,
    sections: { "Memory Files": "# Project Memory\n\nThis project uses Textual for TUI, OpenAI-compatible backends.\nPrefer targeted edits. Always run tests after changes.\n\n# User Preferences\nExplain before implementing. Match Roo Code polish level." } },
  { id: 6, from: "context_builder", to: "store",
    label: "Fetch conversation (1 msg)", type: "context_source", durationMs: 600,
    data: `Reading from MessageStore (in-memory):\n\n1 user\n\nTotal messages: 1` },
  { id: 7, from: "store", to: "context_builder",
    label: "Returned 1 message", type: "context_source", durationMs: 500,
    data: `Conversation history returned from in-memory store.\n\nMessages: 1\nEstimated tokens: 45` },
  // ── Step 8: Context ready → LLM call #1 ──
  { id: 8, from: "agent", to: "context_builder", label: "Context ready (3 msgs) (iter 1)", type: "context_assembly", durationMs: 600,
    data: `Sending to LLM:\n\n1 system, 1 user\n\nTotal messages: 3` },
  { id: 9, from: "context_builder", to: "llm", label: "LLM call #1 (iter 1)", type: "llm_call", durationMs: 1800,
    data: `[System Prompt] + [5 Tools] + [3 Messages]`,
    sections: {
      "System Prompt": `You are ClarAIty, an expert AI coding assistant running inside VS Code.\nBe concise, precise, and always prefer targeted edits over full rewrites.\nNever guess at file contents — read first, then edit.`,
      "Tools": `read_file / write_file / edit_file / list_dir / run_command`,
      "Messages": `[system]\nYou are ClarAIty...\n\n[user]\nCan you edit the multiply function in utils.py to multiply by 3 instead of 2?`,
    } },
  // ══ ITERATION 1: read_file ══════════════════════════════════════════════════
  { id: 10, from: "llm", to: "agent", label: "Tool call: read_file", type: "llm_response", durationMs: 1200,
    data: `Tool call: read_file("utils.py")`,
    thinking: `The user wants to change the multiply function. Before I edit, I need to read the file to see the exact implementation. A targeted edit_file call will be safer than rewriting the whole function.`,
    sections: {
      "Thinking": `The user wants to change the multiply function. Before I edit, I need to read the file to see the exact implementation. A targeted edit_file call will be safer than rewriting the whole function.`,
      "Response": `{ "tool": "read_file", "parameters": { "path": "utils.py" } }`,
    } },
  { id: 11, from: "agent", to: "gating", label: "Gate check: read_file (iter 1)", type: "gate_check", durationMs: 900,
    data: `Tools entering 4-check pipeline:\n\n  [1] read_file\n\nChecks: repeat -> plan_mode -> director -> approval\nResult: ALLOW (auto-approved read)` },
  { id: 12, from: "gating", to: "tools", label: "Approved: read_file (iter 1)", type: "tool_execute", durationMs: 800,
    data: `read_file({ "path": "utils.py" })` },
  { id: 13, from: "tools", to: "agent", label: "Results: read_file (iter 1)", type: "tool_result", durationMs: 1000,
    data: `[read_file]\ndef add(x, y):\n    return x + y\n\ndef multiply(x, y):\n    """Multiply x by 2."""\n    return x * 2\n\ndef subtract(x, y):\n    return x - y` },
  // ══ ITERATION 2: edit_file ════════════════════════════════════════════════
  { id: 14, from: "agent", to: "context_builder", label: "Context ready (5 msgs) (iter 2)", type: "context_assembly", durationMs: 700,
    data: `Sending to LLM:\n\n1 system, 1 user, 1 assistant, 1 tool\n\nTotal messages: 5` },
  { id: 15, from: "context_builder", to: "llm", label: "LLM call #2 (iter 2)", type: "llm_call", durationMs: 1600,
    data: `[System Prompt] + [5 Tools] + [5 Messages]`,
    sections: {
      "System Prompt": `You are ClarAIty...`,
      "Tools": `read_file / write_file / edit_file / list_dir / run_command`,
      "Messages": `[user] Can you edit the multiply function...\n[assistant] <tool_call: read_file("utils.py")>\n[tool] def multiply(x, y): return x * 2`,
    } },
  { id: 16, from: "llm", to: "agent", label: "Tool call: edit_file", type: "llm_response", durationMs: 1200,
    data: `Tool call: edit_file("utils.py", ...)`,
    thinking: `I can see the multiply function: "return x * 2". I'll use edit_file with the exact indented string as old_string for a precise single-line replacement.`,
    sections: {
      "Thinking": `I can see the multiply function: "return x * 2". I'll use edit_file with the exact indented string as old_string for a precise single-line replacement.`,
      "Response": `{ "tool": "edit_file", "parameters": { "path": "utils.py", "old_string": "    return x * 2", "new_string": "    return x * 3" } }`,
    } },
  { id: 17, from: "agent", to: "gating", label: "Gate check: edit_file (iter 2)", type: "gate_check", durationMs: 900,
    data: `Tools entering 4-check pipeline:\n\n  [1] edit_file\n\nChecks: repeat -> plan_mode -> director -> approval\nResult: NEEDS_APPROVAL (write operation)` },
  // ── Approval flow: Gating asks User, User approves ──
  { id: 18, from: "gating", to: "user", label: "Approval required: edit_file", type: "approval", durationMs: 1200,
    data: `Tool: edit_file\nPath: utils.py\nOperation: write\n\nReason: Write operations require user approval.\n\nWaiting for user decision...`,
    sections: {
      "Tool": `edit_file`,
      "Arguments": `{ "path": "utils.py", "old_string": "    return x * 2", "new_string": "    return x * 3" }`,
      "Reason": `Category-based approval: write operations require explicit user consent.\nSafety floor check: passed (not a destructive command).`,
    } },
  { id: 19, from: "user", to: "gating", label: "User approved edit_file", type: "approval", durationMs: 800,
    data: `Decision: APPROVED\nWait time: 2.3s\n\nTool execution will proceed.` },
  { id: 20, from: "gating", to: "tools", label: "Approved: edit_file (iter 2)", type: "tool_execute", durationMs: 800,
    data: `edit_file({ "path": "utils.py", "old_string": "    return x * 2", "new_string": "    return x * 3" })` },
  { id: 21, from: "tools", to: "agent", label: "Results: edit_file (iter 2)", type: "tool_result", durationMs: 900,
    data: `[edit_file]\nSuccess -- 1 change applied.\nFile: utils.py\nLines changed: 1 (line 8)` },
  // ══ ITERATION 3: final response ═══════════════════════════════════════════
  { id: 22, from: "agent", to: "context_builder", label: "Context ready (7 msgs) (iter 3)", type: "context_assembly", durationMs: 700,
    data: `Sending to LLM:\n\n1 system, 1 user, 2 assistant, 2 tool\n\nTotal messages: 7` },
  { id: 23, from: "context_builder", to: "llm", label: "LLM call #3 (iter 3)", type: "llm_call", durationMs: 1400,
    data: `[System Prompt] + [5 Tools] + [7 Messages]`,
    sections: {
      "System Prompt": `You are ClarAIty...`,
      "Tools": `read_file / write_file / edit_file / list_dir / run_command`,
      "Messages": `[user] Can you edit...\n[assistant] read_file\n[tool] <content>\n[assistant] edit_file\n[tool] Success -- 1 change applied`,
    } },
  { id: 24, from: "llm", to: "agent", label: "Final text response", type: "llm_response", durationMs: 1200,
    data: `"I've updated the multiply function in utils.py."`,
    thinking: `The edit succeeded. I'll give a clear before/after summary.`,
    sections: {
      "Thinking": `The edit succeeded. I'll give a clear before/after summary so the user can verify.`,
      "Response": `I've updated the multiply function in utils.py.\n\nBefore: return x * 2\nAfter:  return x * 3`,
    } },
  // ══ TURN END ══════════════════════════════════════════════════════════════
  { id: 25, from: "agent", to: "store", label: "Session persisted", type: "persist", durationMs: 900,
    data: `MessageStore updated (in-memory) + appended to:\n.claraity/sessions/sess_20240402.jsonl\n\nAppended 8 messages` },
  { id: 26, from: "agent", to: "user", label: "Response delivered", type: "request", durationMs: 800,
    data: `Response sent back to user in VS Code.` },
];

// ─── Step styling ───────────────────────────────────────────────────────────────

const STEP_COLORS: Record<StepType, string> = {
  request:          "#FF8A65",
  context_assembly: "#FFB300",
  context_source:   "#FDD835",
  llm_call:         "#AB47BC",
  llm_response:     "#CE93D8",
  gate_check:       "#F06292",
  approval:         "#FF5252",
  tool_execute:     "#26A69A",
  tool_result:      "#4DB6AC",
  persist:          "#EF5350",
  subagent_start:   "#1E88E5",
  subagent_end:     "#1E88E5",
};

const STEP_LABELS: Record<StepType, string> = {
  request:          "Request",
  context_assembly: "Context",
  context_source:   "Source",
  llm_call:         "LLM Call",
  llm_response:     "LLM Response",
  gate_check:       "Gate Check",
  approval:         "Approval",
  tool_execute:     "Tool Execute",
  tool_result:      "Tool Result",
  persist:          "Persist",
  subagent_start:   "SubAgent Start",
  subagent_end:     "SubAgent End",
};

// ─── CSS injection ──────────────────────────────────────────────────────────────

const TRACE_CSS = `
@keyframes trace-node-glow {
  0%, 100% { opacity: 0.7; }
  50% { opacity: 1; }
}
@keyframes trace-flow {
  to { stroke-dashoffset: -20; }
}
@keyframes trace-zzz-1 {
  0% { transform: translate(0px, 0px); opacity: 0.9; }
  100% { transform: translate(6px, -16px); opacity: 0; }
}
@keyframes trace-zzz-2 {
  0% { transform: translate(0px, 0px); opacity: 0.8; }
  100% { transform: translate(9px, -22px); opacity: 0; }
}
@keyframes trace-zzz-3 {
  0% { transform: translate(0px, 0px); opacity: 0.7; }
  100% { transform: translate(12px, -30px); opacity: 0; }
}
@keyframes trace-brain-pulse {
  0%, 100% { r: 12; opacity: 0.6; }
  50% { r: 14; opacity: 1; }
}
@keyframes trace-wrench-spin {
  0%, 100% { transform: rotate(-15deg); }
  50% { transform: rotate(15deg); }
}
@keyframes trace-packet-in {
  0% { opacity: 0; transform: scale(0.3); }
  60% { opacity: 1; transform: scale(1.2); }
  100% { opacity: 1; transform: scale(1); }
}
@keyframes trace-cloud-in {
  0%   { opacity: 0; transform: scale(0.4) translateY(10px); }
  70%  { opacity: 1; transform: scale(1.05) translateY(-2px); }
  100% { opacity: 1; transform: scale(1) translateY(0); }
}
@keyframes trace-dot-bounce {
  0%, 100% { transform: translateY(0); }
  50%       { transform: translateY(-3px); }
}
`;

let traceStylesInjected = false;
function injectTraceStyles() {
  if (traceStylesInjected) return;
  const el = document.createElement("style");
  el.textContent = TRACE_CSS;
  document.head.appendChild(el);
  traceStylesInjected = true;
}

// ─── SVG path helper ────────────────────────────────────────────────────────────

function curvePath(from: NodeDef, to: NodeDef): string {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  // Perpendicular control point for a gentle arc
  const cx = (from.x + to.x) / 2 - dy * 0.18;
  const cy = (from.y + to.y) / 2 + dx * 0.18;
  return `M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}`;
}

// ─── Smooth animation helpers ───────────────────────────────────────────────────

/** Evaluate a quadratic bezier (same control point as curvePath) at parameter t [0,1]. */
function bezierPoint(
  from: { x: number; y: number },
  to: { x: number; y: number },
  t: number
): { x: number; y: number } {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const cx = (from.x + to.x) / 2 - dy * 0.18;
  const cy = (from.y + to.y) / 2 + dx * 0.18;
  const mt = 1 - t;
  return {
    x: mt * mt * from.x + 2 * mt * t * cx + t * t * to.x,
    y: mt * mt * from.y + 2 * mt * t * cy + t * t * to.y,
  };
}

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

// Always-visible edges
const EDGES: [NodeId, NodeId][] = [
  ["user", "agent"],
  ["agent", "context_builder"],
  ["context_builder", "llm"],
  ["context_builder", "store"],  // Context Builder reads conversation from Store
  ["llm", "agent"],      // LLM response returns direct to agent
  ["agent", "gating"],
  ["gating", "user"],    // Approval request: Gating asks User
  ["gating", "tools"],
  ["tools", "agent"],    // Tool results return direct to agent
  ["agent", "store"],
];

// ─── Character: User at laptop ──────────────────────────────────────────────────

function UserChar({ active }: { active: boolean }) {
  const c = active ? "#FF8A65" : "#795548";
  return (
    <g>
      {/* Head */}
      <circle cy={-58} r={13} fill="#FFB74D" stroke={c} strokeWidth={2} />
      {/* Hair */}
      <ellipse cy={-69} rx={11} ry={5} fill="#5D4037" />
      {/* Eyes */}
      <circle cx={-4.5} cy={-59} r={2} fill="#4E342E" />
      <circle cx={4.5} cy={-59} r={2} fill="#4E342E" />
      {/* Smile */}
      <path d="M -5 -51 Q 0 -47 5 -51" stroke="#5D4037" strokeWidth={1.5} fill="none" strokeLinecap="round" />
      {/* Torso */}
      <rect x={-15} y={-43} width={30} height={20} rx={5} fill={active ? "#5C6BC0" : "#3949AB"} />
      {/* Arms */}
      <line x1={-15} y1={-36} x2={-27} y2={-20} stroke={active ? "#5C6BC0" : "#3949AB"} strokeWidth={6} strokeLinecap="round" />
      <line x1={15} y1={-36} x2={27} y2={-20} stroke={active ? "#5C6BC0" : "#3949AB"} strokeWidth={6} strokeLinecap="round" />
      {/* Laptop shell */}
      <rect x={-30} y={-20} width={60} height={40} rx={4} fill={active ? "#546E7A" : "#37474F"} />
      {/* Screen */}
      <rect x={-25} y={-16} width={50} height={30} rx={2} fill={active ? "#1976D2" : "#0D47A1"} />
      {/* Code lines on screen */}
      <rect x={-20} y={-11} width={30} height={3} rx={1} fill={active ? "#64B5F6" : "#1565C0"} opacity={0.8} />
      <rect x={-20} y={-5} width={22} height={3} rx={1} fill={active ? "#64B5F6" : "#1565C0"} opacity={0.6} />
      <rect x={-20} y={1} width={28} height={3} rx={1} fill={active ? "#64B5F6" : "#1565C0"} opacity={0.5} />
      <rect x={-20} y={7} width={18} height={3} rx={1} fill={active ? "#64B5F6" : "#1565C0"} opacity={0.4} />
      {/* Cursor blink */}
      {active && <rect x={10} y={7} width={2} height={3} rx={0.5} fill="#64B5F6" />}
      {/* Hinge */}
      <rect x={-30} y={20} width={60} height={4} rx={2} fill="#263238" />
    </g>
  );
}

// ─── Character: Agent robot ─────────────────────────────────────────────────────

function AgentChar({ active }: { active: boolean }) {
  const headFill = active ? "#1E88E5" : "#1976D2";
  const bodyFill = active ? "#1565C0" : "#0D47A1";
  const eyeFill  = active ? "#E3F2FD" : "#90CAF9";
  return (
    <g>
      {/* Antenna */}
      <line x1={0} y1={-68} x2={0} y2={-82} stroke="#90CAF9" strokeWidth={3} />
      <circle cy={-86} r={6} fill={active ? "#FFD740" : "#78909C"} />
      {/* Head */}
      <rect x={-26} y={-68} width={52} height={44} rx={10} fill={headFill} />
      {/* Eyes */}
      <rect x={-18} y={-56} width={13} height={10} rx={3} fill={eyeFill} />
      <rect x={5} y={-56} width={13} height={10} rx={3} fill={eyeFill} />
      {active && (
        <>
          <rect x={-13} y={-53} width={4} height={4} rx={1} fill="#1976D2" />
          <rect x={10} y={-53} width={4} height={4} rx={1} fill="#1976D2" />
        </>
      )}
      {/* Mouth */}
      {active
        ? <path d="M -10 -37 Q 0 -31 10 -37" stroke="#E3F2FD" strokeWidth={2} fill="none" strokeLinecap="round" />
        : <line x1={-8} y1={-37} x2={8} y2={-37} stroke="#90CAF9" strokeWidth={2} strokeLinecap="round" />
      }
      {/* Body */}
      <rect x={-28} y={-22} width={56} height={50} rx={7} fill={bodyFill} />
      {/* Clipboard on body */}
      <rect x={-20} y={-14} width={40} height={36} rx={3} fill="#E3F2FD" />
      <rect x={-9} y={-18} width={18} height={8} rx={3} fill="#90CAF9" />
      <line x1={-14} y1={-2} x2={14} y2={-2} stroke="#90CAF9" strokeWidth={2} />
      <line x1={-14} y1={5} x2={14} y2={5} stroke="#90CAF9" strokeWidth={2} />
      <line x1={-14} y1={12} x2={8} y2={12} stroke="#90CAF9" strokeWidth={2} />
    </g>
  );
}

function SubAgentChar({ active }: { active: boolean }) {
  const headFill = active ? "#E65100" : "#BF360C";
  const bodyFill = active ? "#D84315" : "#BF360C";
  const eyeFill  = active ? "#FFF3E0" : "#FFCC80";
  return (
    <g>
      {/* Antenna — dimmed (subordinate) */}
      <line x1={0} y1={-68} x2={0} y2={-82} stroke="#FFAB91" strokeWidth={2} />
      <circle cy={-86} r={4} fill={active ? "#FFAB91" : "#78909C"} />
      {/* Head */}
      <rect x={-26} y={-68} width={52} height={44} rx={10} fill={headFill} />
      {/* Eyes */}
      <rect x={-18} y={-56} width={13} height={10} rx={3} fill={eyeFill} />
      <rect x={5} y={-56} width={13} height={10} rx={3} fill={eyeFill} />
      {active && (
        <>
          <rect x={-13} y={-53} width={4} height={4} rx={1} fill="#BF360C" />
          <rect x={10} y={-53} width={4} height={4} rx={1} fill="#BF360C" />
        </>
      )}
      {/* Mouth */}
      {active
        ? <path d="M -10 -37 Q 0 -31 10 -37" stroke="#FFF3E0" strokeWidth={2} fill="none" strokeLinecap="round" />
        : <line x1={-8} y1={-37} x2={8} y2={-37} stroke="#FFAB91" strokeWidth={2} strokeLinecap="round" />
      }
      {/* Body */}
      <rect x={-28} y={-22} width={56} height={50} rx={7} fill={bodyFill} />
      {/* Gear on body (specialist worker) */}
      <circle cy={3} r={16} fill="#FFF3E0" />
      <circle cy={3} r={10} fill={bodyFill} />
      {/* Gear teeth */}
      {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => (
        <rect
          key={deg}
          x={-3} y={-20}
          width={6} height={8}
          rx={1}
          fill="#FFF3E0"
          transform={`rotate(${deg} 0 3)`}
        />
      ))}
      {/* Inner gear dot */}
      <circle cy={3} r={4} fill="#FFF3E0" />
    </g>
  );
}

// ─── Character: Context Builder (factory/assembler with 4 source slots) ─────────

/** Source names as they appear in trace event labels (prefix before ":"). */
const CB_SOURCES = [
  { label: "System Prompt", key: "System Prompt" },
  { label: "CLARAITY.md",   key: "CLARAITY.md" },
  { label: "Knowledge DB",  key: "Knowledge DB" },
  { label: "Memory Files",  key: "Memory Files" },
] as const;

function ContextBuilderChar({ active, activeSource }: { active: boolean; activeSource?: string }) {
  const bodyFill = active ? "#F9A825" : "#F57F17";
  const slotFill = active ? "#FFF8E1" : "#FFF9C4";
  const highlightFill = "#FFECB3";
  const highlightStroke = "#FFD740";
  return (
    <g>
      {/* Gear icon on top */}
      <circle cy={-68} r={11} fill={active ? "#FFD740" : "#FFB300"}
        stroke="#E65100" strokeWidth={1.5}
        style={active ? { animation: "trace-brain-pulse 1.5s ease-in-out infinite" } : {}} />
      {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => (
        <rect key={angle} x={-2} y={-79} width={4} height={6} rx={1}
          fill={active ? "#FFD740" : "#FFB300"}
          transform={`rotate(${angle}, 0, -68)`} />
      ))}
      {/* Body */}
      <rect x={-34} y={-55} width={68} height={96} rx={6} fill={bodyFill} />
      {/* Source slots — 8px font, 16px tall, 60px wide */}
      {CB_SOURCES.map((src, i) => {
        const y = -49 + i * 21;
        const isHighlighted = activeSource === src.key;
        return (
          <g key={i}>
            <rect x={-28} y={y} width={56} height={17} rx={3}
              fill={isHighlighted ? highlightFill : slotFill}
              stroke={isHighlighted ? highlightStroke : "#BF360C"}
              strokeWidth={isHighlighted ? 1.5 : 0.5} />
            <text x={-23} y={y + 12} fontSize={8}
              fill={isHighlighted ? "#5D4037" : "#795548"}
              fontWeight={isHighlighted ? 600 : 500}>
              {src.label}
            </text>
          </g>
        );
      })}
      {/* Output arrow */}
      <polygon points="-8,38 8,38 0,46" fill={active ? "#FFD740" : "#FFB300"} />
    </g>
  );
}

// ─── Character: Tool Gating (security checkpoint) ───────────────────────────────

function GatingChar({ active }: { active: boolean }) {
  const gateFill   = active ? "#E91E63" : "#C2185B";
  const shieldFill = active ? "#FCE4EC" : "#F8BBD0";
  return (
    <g>
      {/* Gate posts */}
      <rect x={-32} y={-30} width={8} height={55} rx={2} fill={gateFill} />
      <rect x={24} y={-30} width={8} height={55} rx={2} fill={gateFill} />
      {/* Post caps (lights) */}
      <circle cx={-28} cy={-34} r={6} fill={active ? "#4CAF50" : "#F44336"} />
      <circle cx={28} cy={-34} r={6} fill={active ? "#4CAF50" : "#F44336"} />
      {/* Barrier bar */}
      <rect x={-28} y={active ? -52 : -10} width={56} height={6} rx={3}
        fill={active ? "#66BB6A" : "#EF5350"} />
      {/* Shield icon */}
      <path d="M 0 -18 L -14 -8 L -14 6 Q -14 20 0 26 Q 14 20 14 6 L 14 -8 Z"
        fill={shieldFill} stroke={gateFill} strokeWidth={2} />
      {/* Check / X inside shield */}
      {active ? (
        <polyline points="-6,4 -1,10 8,-2" stroke="#2E7D32" strokeWidth={3}
          fill="none" strokeLinecap="round" strokeLinejoin="round" />
      ) : (
        <g>
          <line x1={-5} y1={-1} x2={5} y2={9} stroke="#B71C1C" strokeWidth={2.5} strokeLinecap="round" />
          <line x1={5} y1={-1} x2={-5} y2={9} stroke="#B71C1C" strokeWidth={2.5} strokeLinecap="round" />
        </g>
      )}
      {/* "4-CHECK" label */}
      <rect x={-18} y={26} width={36} height={10} rx={3} fill="rgba(0,0,0,0.3)" />
      <text y={34} textAnchor="middle" fontSize={6.5} fill="#FCE4EC" fontWeight="bold">4-CHECK</text>
    </g>
  );
}

// ─── Character: LLM robot (sleeps when idle) ────────────────────────────────────

function LLMChar({ active, sleeping }: { active: boolean; sleeping: boolean }) {
  const headFill = active ? "#8E24AA" : "#9C27B0";
  const bodyFill = active ? "#6A1B9A" : "#7B1FA2";

  return (
    <g>
      {/* Antenna */}
      <line x1={0} y1={-65} x2={0} y2={-80} stroke="#CE93D8" strokeWidth={3} />
      <circle cy={-85} r={7} fill={active ? "#FFD740" : sleeping ? "#555" : "#CE93D8"} />
      {/* Head */}
      <rect x={-34} y={-65} width={68} height={56} rx={12} fill={headFill} />
      {/* Side vents */}
      <rect x={-42} y={-53} width={9} height={22} rx={3} fill={bodyFill} />
      <rect x={33} y={-53} width={9} height={22} rx={3} fill={bodyFill} />
      {/* Eyes */}
      {sleeping ? (
        <>
          <line x1={-20} y1={-38} x2={-8} y2={-38} stroke="#CE93D8" strokeWidth={4} strokeLinecap="round" />
          <line x1={8} y1={-38} x2={20} y2={-38} stroke="#CE93D8" strokeWidth={4} strokeLinecap="round" />
          {/* ZZZ */}
          <text x={36} y={-48} fontSize={10} fill="#9E9E9E" fontWeight="bold"
            style={{ animation: "trace-zzz-1 2.4s ease-in 0s infinite" }}>z</text>
          <text x={40} y={-62} fontSize={13} fill="#757575" fontWeight="bold"
            style={{ animation: "trace-zzz-2 2.4s ease-in 0.7s infinite" }}>z</text>
          <text x={46} y={-78} fontSize={16} fill="#616161" fontWeight="bold"
            style={{ animation: "trace-zzz-3 2.4s ease-in 1.4s infinite" }}>Z</text>
        </>
      ) : (
        <>
          <circle cx={-14} cy={-38} r={9} fill="#fff" />
          <circle cx={14} cy={-38} r={9} fill="#fff" />
          <circle cx={-14} cy={-38} r={4} fill={active ? "#1A237E" : "#4A148C"} />
          <circle cx={14} cy={-38} r={4} fill={active ? "#1A237E" : "#4A148C"} />
          {/* Eye glints */}
          <circle cx={-11} cy={-41} r={1.5} fill="#fff" />
          <circle cx={17} cy={-41} r={1.5} fill="#fff" />
        </>
      )}
      {/* Mouth */}
      {active && !sleeping && (
        <path d="M -12 -20 Q 0 -13 12 -20" stroke="#E1BEE7" strokeWidth={2.5} fill="none" strokeLinecap="round" />
      )}
      {/* Body */}
      <rect x={-28} y={-6} width={56} height={44} rx={7} fill={bodyFill} />
      {/* Brain circuit */}
      <circle cx={0} cy={17} r={12} fill="none" stroke={active ? "#CE93D8" : "#7B1FA2"} strokeWidth={2}
        style={active ? { animation: "trace-brain-pulse 1.5s ease-in-out infinite" } : {}} />
      <line x1={-18} y1={17} x2={-12} y2={17} stroke="#CE93D8" strokeWidth={2} />
      <line x1={12} y1={17} x2={18} y2={17} stroke="#CE93D8" strokeWidth={2} />
      <line x1={0} y1={5} x2={0} y2={9} stroke="#CE93D8" strokeWidth={2} />
      <line x1={0} y1={25} x2={0} y2={30} stroke="#CE93D8" strokeWidth={2} />
      <circle cx={-8} cy={12} r={2} fill={active ? "#CE93D8" : "#7B1FA2"} />
      <circle cx={8} cy={12} r={2} fill={active ? "#CE93D8" : "#7B1FA2"} />
    </g>
  );
}

// ─── Character: Toolbox ─────────────────────────────────────────────────────────

function ToolsChar({ active }: { active: boolean }) {
  return (
    <g>
      {/* Lid */}
      <rect x={-32} y={-28} width={64} height={18} rx={5} fill={active ? "#004D40" : "#00695C"} />
      {/* Handle */}
      <path d="M -13 -28 Q 0 -44 13 -28" stroke={active ? "#80CBC4" : "#4DB6AC"} strokeWidth={5} fill="none" strokeLinecap="round" />
      {/* Latch */}
      <rect x={-7} y={-8} width={14} height={8} rx={2} fill={active ? "#80CBC4" : "#4DB6AC"} />
      {/* Body */}
      <rect x={-36} y={-10} width={72} height={48} rx={7} fill={active ? "#00897B" : "#00796B"} />
      {/* Wrench */}
      <g style={active ? { animation: "trace-wrench-spin 0.8s ease-in-out infinite", transformOrigin: "0px 18px" } : {}}>
        <rect x={-4} y={0} width={8} height={30} rx={4} fill="#B2DFDB" />
        <ellipse cx={0} cy={-2} rx={11} ry={8} fill="#B2DFDB" />
        <ellipse cx={0} cy={30} rx={7} ry={5} fill="#B2DFDB" />
      </g>
      {/* Screwdriver */}
      <line x1={16} y1={2} x2={24} y2={32} stroke="#80CBC4" strokeWidth={4} strokeLinecap="round" />
      <polygon points="16,2 22,-4 26,2" fill="#80CBC4" />
    </g>
  );
}

// ─── Character: Store (MessageStore in-memory + JSONL on disk) ──────────────────

function StoreChar({ active }: { active: boolean }) {
  const bodyFill = active ? "#D32F2F" : "#E53935";
  const innerFill = active ? "#FFCDD2" : "#FFCDD2";
  return (
    <g>
      {/* Cylinder top (database shape) */}
      <ellipse cy={-48} rx={30} ry={10} fill={active ? "#B71C1C" : "#C62828"} />
      {/* Cylinder body */}
      <rect x={-30} y={-48} width={60} height={60} fill={bodyFill} />
      {/* Cylinder bottom */}
      <ellipse cy={12} rx={30} ry={10} fill={bodyFill} />
      {/* Cylinder top highlight */}
      <ellipse cy={-48} rx={30} ry={10} fill="none" stroke={innerFill} strokeWidth={1} opacity={0.5} />
      {/* In-memory label */}
      <rect x={-22} y={-38} width={44} height={11} rx={2} fill="rgba(0,0,0,0.25)" />
      <text y={-30} textAnchor="middle" fontSize={6} fill={innerFill} fontWeight="bold">IN-MEMORY</text>
      {/* Data rows */}
      {[0, 1, 2, 3].map((i) => (
        <rect key={i} x={-20} y={-22 + i * 9} width={i % 2 === 0 ? 34 : 26} height={4} rx={2}
          fill={innerFill} opacity={active && i >= 2 ? 1 : 0.45} />
      ))}
      {/* JSONL indicator at bottom */}
      <rect x={-18} y={16} width={36} height={10} rx={3} fill="rgba(0,0,0,0.3)" />
      <text y={24} textAnchor="middle" fontSize={6} fill={innerFill} fontWeight="bold">.jsonl</text>
      {/* Active write cursor */}
      {active && (
        <rect x={-20} y={14} width={3} height={6} rx={1} fill={innerFill}
          style={{ animation: "trace-node-glow 0.5s ease-in-out infinite" }} />
      )}
    </g>
  );
}

// ─── Thinking Cloud ─────────────────────────────────────────────────────────────
// Positioned above-right of the LLM node (LLM is at 760, 100).
// Cloud center: ~855, 5.  Trail dots connect down to LLM antenna at ~760, 34.

function ThinkingCloud({ thinking }: { thinking: string }) {
  const flat = thinking.replace(/\n+/g, " ").trim();
  const maxChars = 80;
  const preview = flat.length > maxChars ? flat.substring(0, maxChars) + "..." : flat;
  const half = Math.ceil(preview.length / 2);
  const breakAt = preview.lastIndexOf(" ", half + 8);
  const line1 = preview.substring(0, breakAt > 10 ? breakAt : half);
  const line2 = preview.substring(line1.length).trim();

  // Cloud centered directly above LLM (840, 250). Antenna top ~250-72=178.
  // Cloud body around y=85-110, trail dots from y=120 down to antenna at y=178.
  const bumps = [
    { cx: 800, cy: 92, rx: 22, ry: 17 },
    { cx: 830, cy: 84, rx: 28, ry: 21 },
    { cx: 864, cy: 88, rx: 26, ry: 19 },
    { cx: 892, cy: 94, rx: 20, ry: 15 },
  ];

  return (
    <g style={{
      animation: "trace-cloud-in 0.45s cubic-bezier(0.175,0.885,0.32,1.275) forwards",
      transformBox: "fill-box",
      transformOrigin: "840px 100px",
    }}>
      {/* Thought trail dots (descending from cloud to LLM antenna) */}
      {[
        { cx: 840, cy: 126, r: 6 },
        { cx: 840, cy: 142, r: 4.5 },
        { cx: 840, cy: 155, r: 3.5 },
        { cx: 840, cy: 166, r: 2.5 },
      ].map((d, i) => (
        <circle key={i} cx={d.cx} cy={d.cy} r={d.r}
          fill="#4A148C" stroke="#AB47BC" strokeWidth={1.5}
          style={{ animation: `trace-dot-bounce 1.4s ease-in-out ${i * 0.2}s infinite` }}
        />
      ))}

      {/* Cloud fill */}
      {bumps.map((b, i) => (
        <ellipse key={`fill-${i}`} cx={b.cx} cy={b.cy} rx={b.rx} ry={b.ry} fill="#1C0828" />
      ))}
      <rect x={782} y={90} width={126} height={20} fill="#1C0828" />
      <ellipse cx={840} cy={108} rx={58} ry={10} fill="#1C0828" />

      {/* Cloud outlines */}
      {bumps.map((b, i) => (
        <ellipse key={`stroke-${i}`} cx={b.cx} cy={b.cy} rx={b.rx} ry={b.ry}
          fill="none" stroke="#AB47BC" strokeWidth={1.5} opacity={0.75} />
      ))}
      <ellipse cx={840} cy={108} rx={58} ry={10}
        fill="none" stroke="#AB47BC" strokeWidth={1.5} opacity={0.75} />
      <rect x={784} y={91} width={122} height={18} fill="#1C0828" />

      <text x={840} y={100} textAnchor="middle" fontSize={9} fill="#E1BEE7"
        fontFamily="var(--vscode-editor-font-family, monospace)" style={{ pointerEvents: "none" }}>
        {line1}
      </text>
      {line2 && (
        <text x={840} y={110} textAnchor="middle" fontSize={9} fill="#CE93D8"
          fontFamily="var(--vscode-editor-font-family, monospace)" style={{ pointerEvents: "none" }}>
          {line2}
        </text>
      )}
    </g>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────────

export function TracePanel({ onBack, steps: externalSteps, traceEnabled = false, onToggleTrace, onClearTrace }: TracePanelProps) {
  injectTraceStyles();

  // Use real trace data if provided, otherwise fall back to mock.
  // External steps have string from/to; cast is safe because the SVG
  // character lookup silently ignores unknown node IDs.
  const STEPS: TraceStep[] = (externalSteps && externalSteps.length > 0
    ? externalSteps as unknown as TraceStep[]
    : MOCK_STEPS);
  const isLiveData = !!(externalSteps && externalSteps.length > 0);

  const [currentStep, setCurrentStep] = useState(-1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [finished, setFinished] = useState(false);
  const [sideTabIndex, setSideTabIndex] = useState(0);

  // ── Scene swap state (subagent visualization) ──
  const [sceneState, setSceneState] = useState<SceneState>("main");
  const [subagentName, setSubagentName] = useState("");

  // Ref so advance() always sees the latest step count (avoids stale closure)
  const stepsLenRef = useRef(STEPS.length);
  stepsLenRef.current = STEPS.length;

  // ── Packet: continuous RAF-based animation (no teleporting) ──
  // packetPosRef holds the live position; packetPos drives SVG renders.
  // Each new step starts from the current ref position — wherever the
  // packet actually IS — so consecutive steps flow without any jump.
  const packetPosRef = useRef({ x: NODES.user.x, y: NODES.user.y });
  const [packetPos, setPacketPos] = useState(packetPosRef.current);
  const [packetTrail, setPacketTrail] = useState<{ x: number; y: number }[]>([]);
  const [packetColor, setPacketColor] = useState("#fff");
  const [packetVisible, setPacketVisible] = useState(false);
  const animRafRef = useRef<number | null>(null);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current != null) clearTimeout(timerRef.current);
  }, []);

  const cancelPacketAnim = useCallback(() => {
    if (animRafRef.current != null) {
      cancelAnimationFrame(animRafRef.current);
      animRafRef.current = null;
    }
  }, []);

  const advance = useCallback(() => {
    setCurrentStep((prev) => {
      const next = prev + 1;
      if (next >= stepsLenRef.current) {
        setIsPlaying(false);
        setFinished(true);
        return prev;
      }
      return next;
    });
  }, []);

  // RAF animation: starts from the current packet position, follows a bezier
  // to the step's destination. No key remounting — packet moves continuously.
  // Self-referencing steps (from === to) orbit the node instead of traveling.
  useLayoutEffect(() => {
    if (currentStep < 0 || currentStep >= STEPS.length) return;

    const step = STEPS[currentStep];
    const toNode = nodeOf(step.to);
    if (!toNode) return; // unknown node ID — skip animation
    const isSelfRef = step.from === step.to;
    const travelMs = isSelfRef
      ? Math.min(step.durationMs * 0.5, 600)  // shorter for self-ref orbit
      : Math.min(step.durationMs * 0.62, 860);

    cancelPacketAnim();
    setPacketColor(STEP_COLORS[step.type]);
    setPacketVisible(true);
    setSideTabIndex(0);

    // Snapshot the starting position from the live ref (not stale state)
    const fromPos = { ...packetPosRef.current };
    let startTime: number | null = null;
    let lastTrailTime = 0;

    const animate = (time: number) => {
      if (startTime == null) startTime = time;
      const rawT = Math.min((time - startTime) / travelMs, 1);
      const t = easeInOutCubic(rawT);

      let pos: { x: number; y: number };
      if (isSelfRef) {
        // Orbit: small circle around the node (radius 28, one full loop)
        const angle = t * Math.PI * 2;
        pos = {
          x: toNode.x + 28 * Math.cos(angle),
          y: toNode.y + 28 * Math.sin(angle),
        };
      } else {
        pos = bezierPoint(fromPos, toNode, t);
      }

      // Update live ref and trigger a render
      packetPosRef.current = pos;
      setPacketPos({ ...pos });

      // Throttle trail updates to ~30fps to avoid excessive re-renders
      if (time - lastTrailTime > 33) {
        lastTrailTime = time;
        setPacketTrail((prev) => [...prev.slice(-7), { ...pos }]);
      }

      if (rawT < 1) {
        animRafRef.current = requestAnimationFrame(animate);
      }
    };

    animRafRef.current = requestAnimationFrame(animate);
    return cancelPacketAnim;
  }, [currentStep, cancelPacketAnim]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-advance timer when playing
  useEffect(() => {
    if (!isPlaying || currentStep < 0 || currentStep >= STEPS.length) return;
    const step = STEPS[currentStep];
    // Cap playback delay — real durationMs preserved in side panel for diagnostics
    const playbackMs = Math.min(step.durationMs || 800, 1200);
    timerRef.current = setTimeout(advance, playbackMs);
    return clearTimer;
  }, [isPlaying, currentStep, advance, clearTimer]);

  // ── Scene swap: instant swap based on _isSubagentStep transitions ──
  // Bookend steps (subagent_start/end) are main-agent events and display normally.
  // The scene swap triggers when we cross from a non-subagent step into a
  // _isSubagentStep step (and vice versa). No fade — just swap immediately.
  useEffect(() => {
    if (currentStep < 0 || currentStep >= STEPS.length) return;
    const curr = STEPS[currentStep] as any;
    const prev = currentStep > 0 ? (STEPS[currentStep - 1] as any) : null;

    const currIsSub = !!curr._isSubagentStep;
    const prevIsSub = prev ? !!prev._isSubagentStep : false;

    // Entering subagent scene
    if (currIsSub && !prevIsSub && sceneState === "main") {
      setSceneState("sub");
      setSubagentName(curr._subagent || "SubAgent");
    }

    // Exiting subagent scene
    if (!currIsSub && prevIsSub && sceneState !== "main") {
      setSceneState("main");
      setSubagentName("");
    }
  }, [currentStep, sceneState, STEPS]);

  const handlePlay = useCallback(() => {
    if (finished) {
      setFinished(false);
      setCurrentStep(0);
      setIsPlaying(true);
      return;
    }
    if (currentStep < 0) {
      setCurrentStep(0);
      setIsPlaying(true);
      return;
    }
    setIsPlaying(true);
  }, [finished, currentStep]);

  const handlePause = useCallback(() => {
    clearTimer();
    setIsPlaying(false);
  }, [clearTimer]);

  const handleReset = useCallback(() => {
    clearTimer();
    cancelPacketAnim();
    setIsPlaying(false);
    setFinished(false);
    setCurrentStep(-1);
    setPacketVisible(false);
    setPacketTrail([]);
    packetPosRef.current = { x: NODES.user.x, y: NODES.user.y };
    setPacketPos({ x: NODES.user.x, y: NODES.user.y });
    setSceneState("main");
    setSubagentName("");
  }, [clearTimer, cancelPacketAnim]);

  const handleStepClick = useCallback((idx: number) => {
    clearTimer();
    setIsPlaying(false);
    setFinished(false);
    // Set correct scene state for the target step
    const targetStep = STEPS[idx] as any;
    if (targetStep?._isSubagentStep) {
      setSceneState("sub");
      setSubagentName(targetStep._subagent || "SubAgent");
    } else {
      setSceneState("main");
      setSubagentName("");
    }
    setCurrentStep(idx);
  }, [clearTimer, STEPS]);

  // Keyboard navigation: ArrowLeft/ArrowRight for prev/next step
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.key === "ArrowLeft" && currentStep > 0) {
        handleStepClick(currentStep - 1);
      } else if (e.key === "ArrowRight" && currentStep < STEPS.length - 1) {
        handleStepClick(currentStep + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [currentStep, handleStepClick, STEPS.length]);

  // Derived state
  const step = currentStep >= 0 && currentStep < STEPS.length ? STEPS[currentStep] : null;

  // Safe node lookup — returns undefined for unknown IDs (e.g. future "subagent" node)
  const nodeOf = (id: string): NodeDef | undefined => NODES[id as NodeId];

  const isNodeActive = (id: NodeId) =>
    step != null && (step.from === id || step.to === id);

  const isEdgeActive = (a: NodeId, b: NodeId) =>
    step != null &&
    ((step.from === a && step.to === b) || (step.from === b && step.to === a));

  const llmSleeping = !isNodeActive("llm");

  // Extract active source name for Context Builder slot highlighting.
  // Label format: "System Prompt: loaded" → extract "System Prompt"
  const activeSource: string | undefined = (() => {
    if (!step || step.type !== "context_source" || step.from !== "context_builder" || step.to !== "context_builder") return undefined;
    const colonIdx = step.label.indexOf(":");
    return colonIdx > 0 ? step.label.substring(0, colonIdx) : undefined;
  })();

  return (
    <div style={{
      display: "flex", flexDirection: "column", height: "100%",
      background: "var(--vscode-editor-background)",
      color: "var(--vscode-editor-foreground)",
      fontFamily: "var(--vscode-font-family)",
      overflow: "hidden",
      userSelect: "none",  // overridden to "text" in side panel content
    }}>

      {/* ── Header ── */}
      <div style={{
        display: "flex", alignItems: "center", padding: "9px 14px",
        borderBottom: "1px solid var(--vscode-panel-border)",
        gap: 10, flexShrink: 0,
      }}>
        <button
          onClick={onBack}
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--vscode-foreground)", padding: "2px 6px", borderRadius: 4, display: "flex", alignItems: "center" }}
          title="Back to chat"
        >
          <i className="codicon codicon-arrow-left" />
        </button>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Behind the Scenes</span>
        <span style={{ fontSize: 11, opacity: 0.45 }}>See how your request is processed</span>
        {isLiveData && (
          <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 8, background: "#2E7D32", color: "#C8E6C9" }}>LIVE</span>
        )}
        {/* Recording toggle */}
        <button
          onClick={() => onToggleTrace?.(!traceEnabled)}
          title={traceEnabled ? "Trace capture ON (click to disable)" : "Trace capture OFF (click to enable)"}
          style={{
            background: "none", border: "none", cursor: "pointer",
            display: "flex", alignItems: "center", gap: 4,
            padding: "2px 6px", borderRadius: 4,
            color: traceEnabled ? "#EF5350" : "var(--vscode-foreground)",
            opacity: traceEnabled ? 1 : 0.5,
          }}
        >
          <i className={`codicon ${traceEnabled ? "codicon-circle-filled" : "codicon-circle-outline"}`} style={traceEnabled ? { color: "#EF5350" } : {}} />
          <span style={{ fontSize: 10 }}>{traceEnabled ? "REC" : "OFF"}</span>
        </button>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          {step && (
            <span style={{
              fontSize: 11, fontWeight: 700,
              background: STEP_COLORS[step.type], color: "#000",
              padding: "2px 9px", borderRadius: 10,
            }}>
              {STEP_LABELS[step.type]}
            </span>
          )}
          <span style={{ fontSize: 11, opacity: 0.4 }}>
            {currentStep >= 0 ? `${currentStep + 1} / ${STEPS.length}` : `${STEPS.length} steps`}
          </span>
        </div>
      </div>

      {/* ── Enable screen (trace OFF and no data) ── */}
      {!traceEnabled && !isLiveData ? (
        <div style={{
          flex: 1, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center",
          padding: 40, textAlign: "center", gap: 16,
        }}>
          <i className="codicon codicon-pulse" style={{ fontSize: 40, opacity: 0.2 }} />
          <div style={{ fontSize: 14, fontWeight: 600, opacity: 0.7 }}>Trace Capture is Off</div>
          <div style={{ fontSize: 12, opacity: 0.45, maxWidth: 300, lineHeight: 1.6 }}>
            Enable trace capture to see how your requests are processed. Each step of the
            agent pipeline — context assembly, LLM calls, tool execution, approvals — will
            be recorded and visualized here.
          </div>
          <div style={{ fontSize: 10, opacity: 0.3, maxWidth: 300, lineHeight: 1.5 }}>
            Trace data is stored locally in your project's .claraity/sessions/ folder. Nothing is sent to any server.
          </div>
          <button
            onClick={() => onToggleTrace?.(true)}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              background: "#1565C0", border: "none", borderRadius: 6,
              padding: "8px 20px", cursor: "pointer", color: "#fff",
              fontSize: 13, fontWeight: 600, marginTop: 8,
            }}
          >
            <i className="codicon codicon-circle-filled" style={{ color: "#EF5350" }} />
            Enable Trace Capture
          </button>
        </div>
      ) : (<>
      {/* Demo banner (trace ON but showing mock data) */}
      {traceEnabled && !isLiveData && (
        <div style={{
          padding: "6px 14px", fontSize: 11,
          background: "rgba(255,179,0,0.12)", color: "#FFB300",
          borderBottom: "1px solid rgba(255,179,0,0.2)",
          textAlign: "center",
        }}>
          Demo data — send a request in the chat to see your real trace
        </div>
      )}
      {/* ── Main: canvas + detail ── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

        {/* SVG canvas */}
        <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
          {/* Subagent badge */}
          {sceneState === "sub" && (
            <div style={{
              position: "absolute", top: 8, left: "50%", transform: "translateX(-50%)",
              background: "#1565C0", color: "#fff", padding: "3px 12px",
              borderRadius: 12, fontSize: 11, fontWeight: 700, zIndex: 10,
            }}>
              SubAgent: {subagentName}
            </div>
          )}
          <svg
            viewBox={`0 ${VY0} ${VW} ${VH}`}
            preserveAspectRatio="xMidYMid meet"
            style={{ width: "100%", height: "100%", display: "block" }}
          >
            <defs>
              {/* Glow filters per node color */}
              {(Object.values(NODES) as NodeDef[]).map((n) => (
                <filter key={n.id} id={`glow-${n.id}`} x="-60%" y="-60%" width="220%" height="220%">
                  <feFlood floodColor={n.color} floodOpacity="0.4" result="flood" />
                  <feComposite in="flood" in2="SourceGraphic" operator="in" result="colored" />
                  <feGaussianBlur in="colored" stdDeviation="8" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              ))}
            </defs>

            {/* Scene content */}
            <g>

            {/* ── Connection lines ── */}
            {EDGES.map(([a, b]) => {
              const active = isEdgeActive(a, b);
              const d = curvePath(NODES[a], NODES[b]);
              return (
                <g key={`${a}-${b}`}>
                  {/* Dim base line */}
                  <path d={d} stroke="rgba(255,255,255,0.08)" strokeWidth={2} fill="none" strokeDasharray="6 4" />
                  {/* Active animated line */}
                  {active && (
                    <path
                      d={d}
                      stroke={packetColor}
                      strokeWidth={2.5}
                      fill="none"
                      strokeDasharray="6 4"
                      opacity={0.55}
                      style={{ animation: "trace-flow 0.35s linear infinite" }}
                    />
                  )}
                </g>
              );
            })}

            {/* ── Nodes ── */}
            {(Object.values(NODES) as NodeDef[]).map((node) => {
              const active = isNodeActive(node.id);
              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x},${node.y})`}
                  style={active ? {
                    filter: `url(#glow-${node.id})`,
                    animation: "trace-node-glow 2s ease-in-out infinite",
                  } : {}}
                >
                  {/* Background halo */}
                  <circle r={56}
                    fill={active ? `${node.color}12` : "rgba(255,255,255,0.02)"}
                    stroke={node.color}
                    strokeWidth={active ? 2 : 1}
                    opacity={active ? 1 : 0.35}
                  />
                  {/* Character */}
                  {node.id === "user"            && <UserChar           active={active} />}
                  {node.id === "agent" && sceneState === "sub"  && <SubAgentChar     active={active || currentStep >= 0} />}
                  {node.id === "agent" && sceneState !== "sub" && <AgentChar          active={active || currentStep >= 0} />}
                  {node.id === "context_builder" && <ContextBuilderChar active={active} activeSource={activeSource} />}
                  {node.id === "llm"             && <LLMChar            active={active} sleeping={llmSleeping} />}
                  {node.id === "gating"          && <GatingChar         active={active} />}
                  {node.id === "tools"           && <ToolsChar          active={active} />}
                  {node.id === "store"           && <StoreChar          active={active} />}
                  {/* Label (dynamic for Agent node during subagent scene) */}
                  <text
                    y={72}
                    textAnchor="middle"
                    fontSize={12}
                    fontWeight={active ? 700 : 500}
                    fill={node.id === "agent" && sceneState === "sub" ? "#E65100" : node.color}
                    opacity={active ? 1 : 0.5}
                  >
                    {node.id === "agent" && sceneState === "sub"
                      ? `SubAgent: ${subagentName}`
                      : node.label}
                  </text>
                </g>
              );
            })}

            {/* ── Comet trail ── */}
            {packetVisible && packetTrail.map((p, i) => {
              const frac = (i + 1) / packetTrail.length;
              return (
                <circle
                  key={i}
                  cx={p.x}
                  cy={p.y}
                  r={Math.max(2, 8 * frac)}
                  fill={packetColor}
                  opacity={0.06 + 0.22 * frac}
                  style={{ pointerEvents: "none" }}
                />
              );
            })}

            {/* ── Animated packet (RAF-driven, no teleport) ── */}
            {packetVisible && (
              <g>
                {/* Glow halo */}
                <circle cx={packetPos.x} cy={packetPos.y} r={16} fill={packetColor} opacity={0.18} />
                {/* Core */}
                <circle cx={packetPos.x} cy={packetPos.y} r={9}  fill={packetColor} opacity={0.92} />
                {/* Bright center */}
                <circle cx={packetPos.x} cy={packetPos.y} r={3.5} fill="#fff"       opacity={0.85} />
              </g>
            )}

            {/* ── Thinking cloud (above LLM, visible on llm_response steps with thinking) ── */}
            {step?.thinking && step.type === "llm_response" && (
              <ThinkingCloud key={`cloud-${currentStep}`} thinking={step.thinking} />
            )}

            {/* Idle hint */}
            {currentStep < 0 && (
              <text
                x={110} y={420}
                textAnchor="middle"
                fontSize={12}
                fill="rgba(255,255,255,0.2)"
              >
                Press Play to visualize
              </text>
            )}
            </g>{/* end scene fade wrapper */}
          </svg>
        </div>

        {/* ── Detail panel ── */}
        <div style={{
          width: step ? 290 : 0,
          minWidth: 0,
          transition: "width 0.28s cubic-bezier(0.4,0,0.2,1)",
          overflow: "hidden",
          borderLeft: "1px solid var(--vscode-panel-border)",
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          background: "var(--vscode-sideBar-background, var(--vscode-editor-background))",
        }}>
          {step && (
            <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: 14, overflowY: "auto", boxSizing: "border-box" }}>
              {/* Step heading */}
              <div style={{
                fontSize: 12, fontWeight: 700, marginBottom: 4,
                color: STEP_COLORS[step.type],
              }}>
                Step {currentStep + 1}
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, lineHeight: 1.4 }}>
                {step.label}
              </div>
              <div style={{ fontSize: 11, opacity: 0.45, marginBottom: 14 }}>
                {nodeOf(step.from)?.label ?? step.from} &rarr; {nodeOf(step.to)?.label ?? step.to}
              </div>
              {/* Tabbed content for llm_call / llm_response; plain for everything else */}
              {step.sections ? (() => {
                const tabs = Object.keys(step.sections);
                const activeTab = tabs[sideTabIndex] ?? tabs[0];
                const isThinkingTab = activeTab === "Thinking";
                const tabInfo: Record<string, string> = {
                  "System Prompt": "Base instructions sent to the LLM. Includes project rules, tool usage guidelines, and safety constraints.",
                  "Tools": "Tool schemas available to the LLM for this call. Each tool has a name and description.",
                  "Messages": "Conversation history included in the context. This is what the LLM sees as prior turns.",
                  "Thinking": "The LLM's internal reasoning before producing a response. Not shown to the user.",
                  "Response": "The LLM's output: either a text response or tool call instructions.",
                  "Tool": "The tool that requires approval before execution.",
                  "Arguments": "Parameters the LLM wants to pass to the tool.",
                  "Reason": "Why this tool requires user approval (safety category or policy).",
                };
                return (
                  <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
                    {/* Tab bar */}
                    <div style={{ display: "flex", gap: 2, marginBottom: 6, flexWrap: "wrap" }}>
                      {tabs.map((tab, i) => (
                        <button key={tab} onClick={() => setSideTabIndex(i)} style={{
                          fontSize: 11, padding: "3px 10px", borderRadius: 4, border: "none",
                          cursor: "pointer", fontWeight: i === sideTabIndex ? 700 : 400,
                          background: i === sideTabIndex
                            ? (tab === "Thinking" ? "#4A148C" : "rgba(255,255,255,0.12)")
                            : "rgba(255,255,255,0.05)",
                          color: i === sideTabIndex
                            ? (tab === "Thinking" ? "#E1BEE7" : "var(--vscode-editor-foreground)")
                            : "rgba(255,255,255,0.45)",
                          transition: "all 0.15s",
                        }}>
                          {tab === "Thinking" ? "\uD83E\uDDE0 Thinking" : tab}
                        </button>
                      ))}
                    </div>
                    {/* Tab info text */}
                    {tabInfo[activeTab] && (
                      <div style={{ fontSize: 10, opacity: 0.4, marginBottom: 8, lineHeight: 1.4 }}>
                        {tabInfo[activeTab]}
                      </div>
                    )}
                    {/* Tab content — selectable */}
                    <pre style={{
                      flex: 1, fontSize: 11, lineHeight: 1.65,
                      whiteSpace: "pre-wrap", wordBreak: "break-word",
                      background: isThinkingTab ? "rgba(74,20,140,0.2)" : "rgba(255,255,255,0.04)",
                      border: `1px solid ${isThinkingTab ? "rgba(171,71,188,0.4)" : "rgba(255,255,255,0.08)"}`,
                      padding: 12, borderRadius: 6, margin: 0,
                      color: isThinkingTab ? "#E1BEE7" : "var(--vscode-editor-foreground)",
                      overflowY: "auto", fontStyle: isThinkingTab ? "italic" : "normal",
                      userSelect: "text", cursor: "text",
                    }}>
                      {step.sections[activeTab]}
                    </pre>
                  </div>
                );
              })() : (
                <pre style={{
                  flex: 1, fontSize: 11, lineHeight: 1.65,
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  padding: 12, borderRadius: 6, margin: 0,
                  color: "var(--vscode-editor-foreground)", overflowY: "auto",
                  userSelect: "text", cursor: "text",
                }}>
                  {step.data}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Controls footer ── */}
      <div style={{
        borderTop: "1px solid var(--vscode-panel-border)",
        padding: "8px 14px",
        flexShrink: 0,
      }}>
        {/* Step timeline dots — scrollable */}
        <div style={{ overflowX: "auto", marginBottom: 8, paddingBottom: 2 }}>
          <div style={{ display: "flex", gap: 3, alignItems: "center", minWidth: "min-content" }}>
            {STEPS.map((s, i) => (
              <button
                key={s.id}
                onClick={() => handleStepClick(i)}
                title={`Step ${i + 1}: ${s.label}`}
                style={{
                  width: i === currentStep ? 20 : 12,
                  height: 6,
                  borderRadius: 3,
                  border: (s as any)._isSubagentStep ? "1px solid #1E88E5" : "none",
                  cursor: "pointer",
                  padding: 0,
                  flexShrink: 0,
                  transition: "all 0.2s",
                  background:
                    i === currentStep
                      ? STEP_COLORS[s.type]
                      : i < currentStep
                      ? "rgba(255,255,255,0.3)"
                      : "rgba(255,255,255,0.1)",
                }}
              />
            ))}
          </div>
        </div>

        {/* Play controls + navigation */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {/* Play/Pause */}
          {!isPlaying ? (
            <button
              onClick={handlePlay}
              style={{
                display: "flex", alignItems: "center", gap: 5,
                background: "#1565C0", border: "none", borderRadius: 5,
                padding: "5px 12px", cursor: "pointer", color: "#fff",
                fontSize: 11, fontWeight: 600,
              }}
            >
              <i className="codicon codicon-play" />
              {finished ? "Replay" : currentStep < 0 ? "Play" : "Resume"}
            </button>
          ) : (
            <button
              onClick={handlePause}
              style={{
                display: "flex", alignItems: "center", gap: 5,
                background: "#37474F", border: "none", borderRadius: 5,
                padding: "5px 12px", cursor: "pointer", color: "#fff",
                fontSize: 11, fontWeight: 600,
              }}
            >
              <i className="codicon codicon-debug-pause" />
              Pause
            </button>
          )}

          {/* Navigation: First / Prev / Next / Last */}
          <div style={{ display: "flex", gap: 2 }}>
            {[
              { icon: "codicon-chevron-left",  title: "First step",    go: () => handleStepClick(0) },
              { icon: "codicon-arrow-left",     title: "Previous step", go: () => currentStep > 0 && handleStepClick(currentStep - 1) },
              { icon: "codicon-arrow-right",    title: "Next step",     go: () => currentStep < STEPS.length - 1 && handleStepClick(currentStep + 1) },
              { icon: "codicon-chevron-right",  title: "Last step",     go: () => handleStepClick(STEPS.length - 1) },
            ].map((btn) => (
              <button key={btn.title} onClick={btn.go} title={btn.title} style={{
                background: "none", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 4,
                padding: "3px 6px", cursor: "pointer", color: "var(--vscode-foreground)",
                display: "flex", alignItems: "center", fontSize: 12,
              }}>
                <i className={`codicon ${btn.icon}`} />
              </button>
            ))}
          </div>

          {/* Step number input */}
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: 4 }}>
            <input
              type="number"
              min={1}
              max={STEPS.length}
              value={currentStep >= 0 ? currentStep + 1 : ""}
              placeholder="#"
              onChange={(e) => {
                const n = parseInt(e.target.value, 10);
                if (n >= 1 && n <= STEPS.length) handleStepClick(n - 1);
              }}
              style={{
                width: 48, padding: "3px 6px", fontSize: 11,
                background: "var(--vscode-input-background, rgba(255,255,255,0.08))",
                color: "var(--vscode-input-foreground, #fff)",
                border: "1px solid var(--vscode-input-border, rgba(255,255,255,0.15))",
                borderRadius: 4, textAlign: "center",
              }}
            />
            <span style={{ fontSize: 10, opacity: 0.4 }}>/ {STEPS.length}</span>
          </div>

          {currentStep >= 0 && (
            <button
              onClick={handleReset}
              style={{
                background: "none",
                border: "1px solid rgba(255,255,255,0.15)",
                borderRadius: 5, padding: "4px 10px",
                cursor: "pointer", color: "var(--vscode-foreground)",
                fontSize: 11, marginLeft: "auto",
              }}
            >
              Reset
            </button>
          )}
          {isLiveData && onClearTrace && (
            <button
              onClick={onClearTrace}
              title="Delete trace data for this session"
              style={{
                background: "none",
                border: "1px solid rgba(239,83,80,0.3)",
                borderRadius: 5, padding: "4px 10px",
                cursor: "pointer", color: "#EF5350",
                fontSize: 11, marginLeft: currentStep < 0 ? "auto" : undefined,
              }}
            >
              Clear Trace
            </button>
          )}
        </div>
      </div>
      </>)}
    </div>
  );
}

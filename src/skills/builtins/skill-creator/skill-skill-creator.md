---
name: Skill Creator
description: >
  Create new skills, modify and improve existing skills, and measure skill
  performance. Use when users want to create a skill from scratch, edit or
  optimize an existing skill, run evals to test a skill, benchmark skill
  performance, or optimize a skill's description for better triggering
  accuracy. Also trigger when the user says "turn this into a skill",
  "make a skill for", "new skill", or wants to capture a repeated workflow.
category: development
tags: [skill, create, eval, benchmark, optimize]
allowed-tools: [run_command, read_file, write_file, edit_file]
arguments: [intent]
argument-hint: "[intent: what the skill should do]"
---

# Skill Creator

A skill for creating new skills and iteratively improving them.

At a high level, the process goes like this:

- Decide what the skill should do and roughly how
- Write a draft
- Create a few test prompts and run the agent with the skill on them
- Help the user evaluate results both qualitatively and quantitatively
  - While runs happen in the background, draft quantitative evals if there
    aren't any. Then explain them to the user.
  - Use the `eval-viewer/generate_review.py` script to show results for the
    user to review, and let them examine quantitative metrics.
- Rewrite the skill based on feedback
- Repeat until satisfied
- Expand test set and try again at larger scale

Your job is to figure out where the user is in this process and help them
progress. Maybe they want to create from scratch. Maybe they already have
a draft. Maybe they want to optimize triggering. Be flexible.

After the skill is done, offer to run the description optimizer to improve
triggering accuracy.

## Communicating with the user

Pay attention to context cues about the user's technical level. In the
default case:
- "evaluation" and "benchmark" are borderline but OK
- For "JSON" and "assertion", see serious cues from the user that they know
  what those are before using them without explanation

It's OK to briefly explain terms if you're in doubt.

---

## Creating a skill

### Capture Intent

Start by understanding the user's intent. The current conversation might
already contain a workflow the user wants to capture (e.g., they say "turn
this into a skill"). If so, extract answers from conversation history first
-- the tools used, the sequence of steps, corrections the user made. The
user may need to fill gaps, and should confirm before proceeding.

1. What should this skill enable the agent to do?
2. When should this skill trigger? (what user phrases/contexts)
3. What's the expected output format?
4. Should we set up test cases to verify it works? Skills with objectively
   verifiable outputs (file transforms, data extraction, code generation)
   benefit from test cases. Skills with subjective outputs (writing style)
   often don't. Suggest the appropriate default but let the user decide.

### Interview and Research

Proactively ask about edge cases, input/output formats, example files,
success criteria, and dependencies. Wait to write test prompts until you've
got this part ironed out.

### Write the skill

Based on the user interview, generate the full skill directory.

**ClarAIty skill directory layout:**

```
.claraity/skills/
+-- skill-name/
    +-- skill-skill-name.md        # Required: main file with YAML frontmatter
    +-- scripts/                   # Optional: executable helper scripts
    +-- references/                # Optional: docs loaded into context as needed
    +-- agents/                    # Optional: subagent prompts
    +-- assets/                    # Optional: templates, icons, files
```

**ClarAIty frontmatter schema (all YAML between `---` delimiters):**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Human-readable skill name |
| `description` | Yes | When/why to use it. This is the primary trigger mechanism. |
| `category` | No | Default: "general". Used for sorting in the skill picker. |
| `tags` | No | Searchable tags as a YAML list. |
| `author` | No | Skill creator/maintainer. |
| `arguments` | No | Named argument placeholders (list of strings). |
| `argument-hint` | No | UI hint for argument format shown in the picker. |
| `disable-model-invocation` | No | If true, skill runs without calling the LLM. |
| `allowed-tools` | No | Informational list. Does NOT bypass tool approval. |

**Naming convention:** The directory name and main file must match:
`my-skill/skill-my-skill.md`. The directory name becomes the skill's `id`
and is used for slash-command invocation (`/my-skill args`).

### Description Writing Guide

The `description` field in frontmatter is the primary mechanism that
determines whether the agent invokes a skill. It appears in the
`available_skills` list that the agent sees on every turn.

**Key principles:**

1. **Be pushy** -- err toward over-triggering. Instead of "Generate PR
   descriptions", write "Generate PR descriptions from branch changes. Use
   when the user wants to create a pull request, write a PR summary,
   describe changes for review, prepare a merge request, or summarize
   their branch -- even if they don't say 'PR' explicitly."

2. **Include trigger phrases** -- list 3-5 specific things a user might say
   that should activate this skill.

3. **Include anti-triggers** -- if there's a common adjacent query that
   should NOT trigger this skill, say so. "Do NOT use for simple git log
   or diff commands."

4. **Keep it under 100 words** -- long descriptions hurt more than they
   help. Be dense, not verbose.

### Preprocessing (Shell Commands)

Skills can run shell commands during preprocessing to gather dynamic
context before the LLM sees the skill body.

**Inline syntax:** An exclamation mark directly followed by a backtick-wrapped
command (no space between the exclamation mark and the opening backtick).

**Fenced block syntax:** A fenced code block whose opening fence is three
backticks followed immediately by an exclamation mark. Each line inside
the block becomes a separate command.

**Key rules:**
- Shell preprocessing runs BEFORE argument substitution. This means
  `$ARGUMENTS` and `$varname` are NOT available inside shell commands.
  Use `${varname:-default}` shell syntax for argument-dependent commands.
- Each command has a 30-second timeout and 10KB output cap.
- All commands require user approval before execution.
- Commands run asynchronously (non-blocking).
- Use preprocessing for: git state, dependency versions, project config,
  file listings, test results -- anything that gives the LLM useful context.

### Progressive Disclosure

Skills use a three-level loading system:
1. **Metadata** (name + description) -- always in context (~100 words)
2. **Skill body** -- in context when skill triggers (keep under 500 lines)
3. **Bundled resources** -- loaded as needed (unlimited; scripts can
   execute without being loaded into context)

**Patterns:**
- Keep the main file under 500 lines. If approaching this, add hierarchy
  with clear pointers to reference files.
- Reference files should be clearly linked from the main file with guidance
  on when to read them.
- For large reference files (>300 lines), include a table of contents.

**Domain organization:** When a skill supports multiple domains, organize
by variant:
```
cloud-deploy/
+-- skill-cloud-deploy.md (workflow + selection)
+-- references/
    +-- aws.md
    +-- gcp.md
    +-- azure.md
```
The agent reads only the relevant reference file.

### Writing Style

Try to explain to the model WHY things are important instead of
heavy-handed MUSTs. Use theory of mind and make the skill general, not
narrow to specific examples. Start by writing a draft, then review it
with fresh eyes and improve.

### Argument Substitution

Skills support these placeholder types:
- `$ARGUMENTS` -- the full raw argument string
- `$varname` -- named argument from the `arguments` frontmatter list
- `$0`, `$1`, `$2` -- positional arguments

Example: if `arguments: [scope, issue]` and the user types
`/my-skill backend 42`, then `$scope` = "backend", `$issue` = "42",
`$0` = "backend", `$1` = "42", `$ARGUMENTS` = "backend 42".

---

## Test Cases

After writing the skill draft, come up with 2-3 realistic test prompts --
the kind of thing a real user would actually say. Share them with the user:
"Here are test cases I'd like to try. Do these look right, or should we
add more?" Then run them.

Save test cases to `evals/evals.json`. Don't write assertions yet -- just
the prompts. You'll draft assertions in the next step while runs are in
progress.

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "User's task prompt",
      "expected_output": "Description of expected result",
      "files": []
    }
  ]
}
```

See `references/schemas.md` for the full schema (including the `expectations`
field, which you'll add later).

---

## Running and Evaluating Test Cases

This section is one continuous sequence -- don't stop partway through.

Put results in `<skill-name>-workspace/` as a sibling to the skill
directory. Within the workspace, organize by iteration (`iteration-1/`,
`iteration-2/`, etc.) and within that, each test case gets a directory
(`eval-0/`, `eval-1/`, etc.). Create directories as you go.

### Step 1: Spawn all runs (with-skill AND baseline) in the same turn

For each test case, spawn two subagents in the same turn -- one with the
skill, one without. Launch everything at once so it finishes around the
same time.

**With-skill run:**
```
Execute this task:
- Skill path: <path-to-skill>
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>/with_skill/outputs/
- Outputs to save: <what the user cares about>
```

**Baseline run** (same prompt, no skill):
- **Creating a new skill**: no skill at all. Same prompt, save to
  `without_skill/outputs/`.
- **Improving an existing skill**: the old version. Before editing,
  snapshot the skill, then point the baseline subagent at the snapshot.
  Save to `old_skill/outputs/`.

Write an `eval_metadata.json` for each test case. Give each eval a
descriptive name. If this iteration uses new eval prompts, create these
files for each new eval directory.

```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "assertions": []
}
```

### Step 2: While runs are in progress, draft assertions

Don't wait for runs to finish. Draft quantitative assertions for each test
case and explain them to the user.

Good assertions are objectively verifiable and have descriptive names.
Subjective skills (writing style, design quality) are better evaluated
qualitatively -- don't force assertions onto things that need human
judgment.

Update `eval_metadata.json` and `evals/evals.json` with the assertions.

### Step 3: As runs complete, capture timing data

When each subagent task completes, you receive a notification with
`total_tokens` and `duration_ms`. Save immediately to `timing.json`:

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

This is the only opportunity to capture this data -- it comes through the
task notification and isn't persisted elsewhere.

### Step 4: Grade, aggregate, and launch the viewer

> **Note:** Steps 4.2 and 4.4 reference `scripts/aggregate_benchmark.py`
> and `eval-viewer/generate_review.py` which are planned Phase 2 additions.
> If unavailable, perform grading manually (step 4.1) and present results
> directly in the conversation. The core loop still works without them.

Once all runs are done:

1. **Grade each run** -- spawn a grader subagent that reads
   `agents/grader.md` and evaluates assertions against outputs. Save
   results to `grading.json` in each run directory. The grading.json
   `expectations` array must use fields `text`, `passed`, and `evidence`
   (the viewer depends on these exact field names). For assertions that can
   be checked programmatically, write and run a script rather than
   eyeballing it.

2. **Aggregate into benchmark** (requires `scripts/aggregate_benchmark.py`):
   ```bash
   python scripts/aggregate_benchmark.py <workspace>/iteration-N --skill-name <name>
   ```
   This produces `benchmark.json` and `benchmark.md`. Put each with_skill
   version before its baseline counterpart.

3. **Analyst pass** -- read benchmark data and surface patterns the
   aggregate stats might hide. See `agents/analyzer.md` for what to look
   for: non-discriminating assertions, high-variance evals, time/token
   tradeoffs.

4. **Launch the viewer** (requires `eval-viewer/generate_review.py`):
   ```bash
   python eval-viewer/generate_review.py \
     <workspace>/iteration-N \
     --skill-name "my-skill" \
     --benchmark <workspace>/iteration-N/benchmark.json
   ```
   For iteration 2+, also pass `--previous-workspace <workspace>/iteration-<N-1>`.

   **Headless environments:** Use `--static <output_path>` to write a
   standalone HTML file instead of starting a server.

5. **Tell the user**: "I've opened the results in your browser. There are
   two tabs -- 'Outputs' lets you click through each test case and leave
   feedback, 'Benchmark' shows the quantitative comparison. When you're
   done, come back and let me know."

### What the user sees in the viewer

The "Outputs" tab shows one test case at a time:
- **Prompt**: the task given
- **Output**: files the skill produced, rendered inline
- **Previous Output** (iteration 2+): collapsed, showing last iteration
- **Formal Grades** (if grading was run): collapsed assertion pass/fail
- **Feedback**: textbox that auto-saves
- **Previous Feedback** (iteration 2+): comments from last time

The "Benchmark" tab shows stats: pass rates, timing, token usage per
configuration, with per-eval breakdowns and analyst observations.

Navigation via prev/next buttons or arrow keys. "Submit All Reviews"
saves all feedback to `feedback.json`.

### Step 5: Read the feedback

When the user says they're done, read `feedback.json`:

```json
{
  "reviews": [
    {"run_id": "eval-0-with_skill", "feedback": "missing axis labels", "timestamp": "..."},
    {"run_id": "eval-1-with_skill", "feedback": "", "timestamp": "..."}
  ],
  "status": "complete"
}
```

Empty feedback means the user thought it was fine. Focus improvements on
test cases where the user had specific complaints.

---

## Improving the Skill

This is the heart of the loop.

### How to think about improvements

1. **Generalize from the feedback.** You and the user are iterating on a
   few examples because it's fast, but the skill will be used across many
   different prompts. Rather than fiddly overfitting changes or oppressive
   MUSTs, try branching out with different metaphors or patterns. It's
   cheap to try.

2. **Keep the prompt lean.** Remove things that aren't pulling their
   weight. Read the transcripts, not just final outputs -- if the skill
   is making the model waste time on unproductive steps, remove those
   instructions.

3. **Explain the why.** LLMs are smart. They have good theory of mind.
   When given reasoning, they go beyond rote instructions. If you find
   yourself writing ALWAYS or NEVER in all caps, reframe and explain the
   reasoning instead.

4. **Look for repeated work across test cases.** Read transcripts and
   notice if subagents all independently wrote similar helper scripts.
   If all 3 test cases resulted in writing a `create_chart.py`, bundle
   that script in `scripts/` and tell the skill to use it.

### The iteration loop

After improving the skill:

1. Apply improvements
2. Rerun all test cases into `iteration-<N+1>/`, including baselines.
   For new skills, baseline is always `without_skill`. For improvements,
   use your judgment on what baseline makes sense.
3. Launch the reviewer with `--previous-workspace` pointing at the
   previous iteration
4. Wait for the user to review
5. Read new feedback, improve again, repeat

Keep going until:
- The user says they're happy
- Feedback is all empty (everything looks good)
- You're not making meaningful progress

---

## Advanced: Blind Comparison

For rigorous comparison between two skill versions, there's a blind
comparison system. Read `agents/comparator.md` and `agents/analyzer.md`
for details. Give two outputs to an independent agent without revealing
which skill produced which, and let it judge quality.

This is optional and most users won't need it. The human review loop is
usually sufficient.

---

## Description Optimization

After the skill is working well, offer to optimize the description for
better triggering accuracy. See `references/description-optimization.md`
for the full process (generate trigger eval queries, review with user,
run the optimization loop, apply results).

---

## Validation

Before declaring a skill production-ready, run the structural validator:

```bash
python scripts/quick_validate.py <path-to-skill-directory>
```

This checks:
- Valid YAML frontmatter with required fields (name, description)
- Main file naming convention (`skill-<dirname>.md`)
- File size limits (main file under 500 lines)
- Description length (reasonable for triggering)
- Referenced subdirectories exist if mentioned in the body

---

## Reference files

- `agents/grader.md` -- Evaluate assertions against outputs
- `agents/comparator.md` -- Blind A/B comparison
- `agents/analyzer.md` -- Analyze benchmark patterns
- `references/schemas.md` -- JSON structures for evals.json, grading.json, etc.
- `references/description-optimization.md` -- Trigger description optimization

---

## Core loop (for emphasis)

- Figure out what the skill is about
- Draft or edit the skill
- Run the agent with the skill on test prompts
- With the user, evaluate the outputs:
  - Create benchmark.json and run `eval-viewer/generate_review.py` to
    help the user review them
  - Run quantitative evals
- Repeat until you and the user are satisfied

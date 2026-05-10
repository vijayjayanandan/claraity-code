# Description Optimization

After creating or improving a skill, offer to optimize the description
for better triggering accuracy.

> **Note:** Steps 2-3 require `assets/eval_review.html` and
> `scripts/run_loop.py` which are Phase 2/3 additions. If these are not
> available, perform description optimization manually by testing trigger
> phrases and iterating on the description text.

## Step 1: Generate trigger eval queries

Create 20 eval queries -- a mix of should-trigger and should-not-trigger.

```json
[
  {"query": "the user prompt", "should_trigger": true},
  {"query": "another prompt", "should_trigger": false}
]
```

Queries must be realistic -- something a user would actually type. Include
file paths, personal context, column names, company names. Use casual
speech, abbreviations, typos. Mix different lengths. Focus on edge cases.

**For should-trigger (8-10):** Different phrasings of the same intent,
some formal, some casual. Cases where the user doesn't explicitly name
the skill but clearly needs it.

**For should-not-trigger (8-10):** Near-misses -- queries that share
keywords but need something different. Don't make them obviously
irrelevant ("Write a fibonacci function" as a negative for a PDF skill
is too easy).

## Step 2: Review with user

Present the eval set to the user for review using the HTML template in
`assets/eval_review.html`. Replace `__EVAL_DATA_PLACEHOLDER__` with the
JSON array and `__SKILL_NAME_PLACEHOLDER__` / `__SKILL_DESCRIPTION_PLACEHOLDER__`
with the skill's details. The user can edit queries, toggle should-trigger,
add/remove entries, then click "Export Eval Set".

## Step 3: Run the optimization loop

```bash
python scripts/run_loop.py \
  --eval-set <path-to-trigger-eval.json> \
  --skill-path <path-to-skill> \
  --max-iterations 5 \
  --verbose
```

This splits the eval set into 60% train / 40% held-out test, evaluates
the current description (running each query 3 times for reliability),
then proposes improvements based on failures. It re-evaluates each new
description on both train and test, iterating up to 5 times. Best
description is selected by test score to avoid overfitting.

## Step 4: Apply the result

Take `best_description` from the output and update the skill's frontmatter.
Show the user before/after and report the scores.

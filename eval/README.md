# Gold set and labelling guide

`gold/gold.jsonl` holds hand labels for a random sample of announcements. Each line is one
release, keyed by its SEC accession number. The model is scored against these labels, so they
must follow the **same rules the model is given** (`backend/prompts/extract_v1.md`).

## Current label set: model-produced, not human

At the owner's request, the labels currently used are **`gold/claude_labels.jsonl`, produced by
Claude (Opus 5.5)**, not by a human. `labeller` on every record says so, and every eval run
stores the label file and labellers (`GET /evals` returns them).

What this means for the results:

- Scores against these labels measure **agreement with a stronger model applying the same written
  rules**, not accuracy against human judgement. Report them as "agreement with Claude labels".
- The labels are useful for comparing extraction models and prompt versions with each other.
  They cannot show errors that both models share.
- The 150 releases are the first 150 in the same seeded order `eval label` uses. Parallel
  labelling agents read only the release texts (never the evaluated model's outputs) and wrote
  a one-line evidence note for each label.
- A human-labelled `gold/gold.jsonl` can be added at any time with `eval label`. Scoring the two
  label sets against each other would then measure how far the Claude labels can be trusted.
- After the agents finished, a consistency review changed 7 labels so the same rule was applied
  across batches. Each change is recorded in that record's `notes` as `[review: ...]`.

## Results so far (prompt v1, 150 Claude-labelled releases)

Agreement with the Claude labels. The "always-majority" column is the score of always answering
the most common label; only the gap above it means anything.

| Field | gpt-6-luna | gpt-5.6-luna | Always-majority |
|---|---|---|---|
| guidance_direction | 91.3% | 90.7% | 52.7% (`not_mentioned`) |
| revenue_vs_expectation | 94.0% | 93.3% | 84.7% (`unknown`) |
| eps_vs_expectation | 94.7% | 94.7% | 87.3% (`unknown`) |
| management_tone MAE | 0.139 | 0.214 | |
| Schema failures | 0% | 0% | |
| Cost per release | $0.0013 | $0.0027 | |
| Latency p50 / p95 | 6.4s / 9.2s | 5.8s / 8.2s | |

Readings:

- Guidance direction is the field where the models add real information (91% vs 53%).
- Most guidance disagreements are releases where headline metrics moved in opposite directions,
  for example sales reaffirmed but EPS cut by a one-off charge. These are genuinely ambiguous
  under the written rules.
- Beat/miss agreement is high mostly because both sides say `unknown`.
- The cheaper `gpt-6-luna` is at least as good as `gpt-5.6-luna` on every field, at half the cost.
- Run-to-run noise is real. Re-scoring the same 20 releases moved guidance agreement from 100% to
  90% with no change to model or prompt, which is why the regression gate uses a 10-point
  threshold on mean accuracy.

## How to label

From `backend/`:

```bash
uv run newsalpha eval label --n 10
```

- Releases appear in a fixed random order (seeded), so the sample is reproducible.
- Every answer is written to `gold/gold.jsonl` immediately; quit (`q`) at any time and resume later.
- `s` skips a release (recorded in `gold/skipped.txt`, not shown again), e.g. if it is not really
  an earnings release or you cannot decide.
- The model's answer is never shown, so it cannot anchor you.

Target: 100 to 200 labels. Around 2 to 3 minutes each: the headline, the CEO quote and the outlook
section are usually enough; page through the full text only when guidance is unclear.

## Rules (same as the model's)

Use **only the text**. Do not use what you know about the company, analyst consensus, the share
price reaction or later events.

**Guidance direction**, compared with the company's previous outlook as described in the text:
- `raised` / `lowered`: the release says the outlook went up / down (e.g. "raises full-year EPS
  guidance to $5.10-$5.20 from $4.90-$5.00").
- `maintained`: the release says the outlook is unchanged / reaffirmed.
- `withdrawn`: the release withdraws or suspends guidance.
- `not_mentioned`: no forward guidance, or new guidance with no stated comparison.

**Revenue / EPS vs expectations**: `beat`, `inline` or `miss` only when the release itself compares
the result with expectations, consensus, or the company's own prior guidance ("above the high end
of our guidance range"). Year-over-year growth is not a comparison with expectations. Otherwise
`unknown`.

**Management tone**, -1 to 1, from management's own language (quotes, outlook commentary), not
from the numbers alone. Rough anchors: -1 alarmed, -0.5 cautious/defensive, 0 neutral boilerplate,
0.5 upbeat, 1 exuberant. Steps of 0.25 are plenty.

## Evaluating models

```bash
uv run newsalpha eval run --model gpt-6-luna --prompt-version v1
uv run newsalpha eval run --model gpt-5.6-luna --prompt-version v1
```

Only gold releases a model has not yet processed are sent to the API. Results are stored in
`eval_runs` and served at `GET /evals`.

## Regression check

```bash
uv run newsalpha eval baseline --subset 20     # freeze 20 gold releases + reference scores
uv run newsalpha eval regress                   # re-score; exit 1 on a drop beyond the threshold
```

`baseline` copies those releases' texts into `gold/texts/` (public SEC filings) so the check runs in
CI without the database. CI runs it only when the `OPENAI_API_KEY` repository secret is set
(about $0.03 per run).

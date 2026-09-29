# Gold set and labelling guide

`gold/gold.jsonl` holds hand labels for a random sample of announcements. Each line is one
release, keyed by its SEC accession number. The model is scored against these labels, so they
must follow the **same rules the model is given** (`backend/prompts/extract_v1.md`).

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

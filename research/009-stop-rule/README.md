# 009 · Stop rule 

Artifact for the Harness Layer field note of the same name. Everything here reproduces the
tables and figures in the note. No network, no model calls; a few minutes on a laptop.

## What is here

| File | What |
|---|---|
| `adaptive_vs_fixed.py` | The original CDV benchmark, restored verbatim from public history (`git show b8a219f:benchmarks/adaptive_vs_fixed.py` in [azank1/cdv](https://github.com/azank1/cdv)); one import renamed `loopllm` → `cdv`. |
| `results_original.md` | The table as published at that commit. |
| `extend.py` | Noise sweep (σ ∈ {0.02, 0.05, 0.10, 0.15, 0.20}) × 10 seeds, plus the cold-start sweep. Writes `results.json`. |
| `extend2.py` | Three noise-robust stop rules (confirm-2, smooth-2, margin +0.05) on the same seeds. Writes `results2.json`. |
| `results.json`, `results2.json` | The raw numbers behind Tables 1 and 2 (mean and sd over seeds). |
| `charts.py` | Generates the four figures as SVG (rendered with headless Chrome; no plotting library). |
| `figures/` | The four figures as published. |

## Reproduce

```bash
git clone https://github.com/azank1/cdv && cd cdv && git checkout 356d496
uv sync                                   # or: python -m venv .venv && .venv/bin/pip install -e .
PYTHONPATH=src .venv/bin/python /path/to/research/009-stop-rule/adaptive_vs_fixed.py   # the replication
PYTHONPATH=src .venv/bin/python /path/to/research/009-stop-rule/extend.py 2>/dev/null   # noise + cold start (~1 min)
PYTHONPATH=src .venv/bin/python /path/to/research/009-stop-rule/extend2.py 2>/dev/null  # the cheap fixes
python3 /path/to/research/009-stop-rule/charts.py                                       # writes fig1..4.html next to the script
```

The replication prints the published table to the digit. The two extension scripts print one summary
line per noise level to stderr and write JSON next to themselves.

## Definitions

- **true reach**: the hidden, noiseless quality curve is ≥ 0.80 at the step the loop stopped.
- **observed reach**: the noisy score the loop saw was ≥ 0.80 at that step.
- **confirm-k**: stop at the first run of *k* consecutive observed scores ≥ 0.80.

Python 3.12; `cdv` at `356d496`. MIT, like the rest of this repo.

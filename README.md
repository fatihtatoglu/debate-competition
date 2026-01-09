# Debate Competition

This project prepares data for a simple LLM debate experiment.

## Setup

If Python is not installed, install it first:

```bash
sudo apt update && sudo apt upgrade
sudo apt install python3 -y
python3 --version
```

Create and activate a virtual environment:

```bash
sudo apt install python3-venv -y
python3 -m venv .venv
source .venv/bin/activate
```

## Technical Notes and Run

Install dependencies:

```bash
pip install -r requirements.txt
```

Prepare a `.env` file (see `.env.example`):

```bash
cp .env.example .env
```

Required `.env` fields:

- `TOPIC`
- `CONDITIONS` (optional; additional constraints like geography or assumptions)
- `LANG_CODE` (output language code: tr, en, de)
- `MODEL_A_BACKEND` / `MODEL_B_BACKEND` (local or online)
- `LOCAL_BASE_URL` (for local backend)
- `ONLINE_BASE_URL` (for online backend)
- `MODEL_A_MODEL` / `MODEL_B_MODEL`
- `JUDGE_MODELS` (comma-separated judge model list)
- `JUDGE_BACKENDS` (comma-separated list, must match JUDGE_MODELS)
- `JUDGE_BLIND` (true/false)
- `API_KEY` (required if any backend is online)

Run:

```bash
python debate_experiment.py
```

Generate an HTML report from a JSONL output:

```bash
python render_html.py outputs/out.jsonl --output outputs/out.html
```

### Multiple Runs With Different Configs

If you want to run several model setups, use multiple `.env` files and load them before each run:

```bash
set -a; source .env.a; set +a; python debate_experiment.py
set -a; source .env.b; set +a; python debate_experiment.py
```

Batch example:

```bash
for f in .env.a .env.b .env.c .env.d .env.e; do
  bash -lc 'set -a; source "$1"; set +a; python debate_experiment.py' _ "$f"
done
```

### Prompts

Prompts are loaded from `prompts/model_a/` and `prompts/model_b/`. Each prompt uses:

- `{{TOPIC}}` for the debate topic.
- `{{CONDITIONS}}` for extra constraints, like limiting the answer to a specific country or context.

Set these values in `.env`. Example:

```ini
TOPIC=Remote work is more productive than working from an office.
CONDITIONS=Consider only the conditions in New Zealand.
```

### Output Format

Each run produces a single-line JSONL file under `outputs/`. Each line represents one debate and includes `rounds`, `evaluation`, and `result`. The jury always returns JSON only; model A/B outputs are plain text.

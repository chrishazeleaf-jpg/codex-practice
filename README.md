# ATLAS

A personal AI that builds itself. See [ROADMAP.md](ROADMAP.md) for where it is going.

## The Auto Forge

- **Blood Hound** researches the live web and turns findings into work orders.
- **Forge Director** assigns each order to the best engineer, escalates struggles to Blood
  Hound, and fails an order after 3 struggles so it surfaces to a human instead of looping.
- **Engineers** (FORGE-1/2/3) each work in their own git worktree with file and command
  tools. An order lands on the `atlas-forge` branch only when the full test suite passes.
- **Budget**: every model call is priced; agents pause when the daily cap is reached.

## Run it (Ubuntu)

```bash
git clone https://github.com/chrishazeleaf-jpg/codex-practice atlas && cd atlas
python3 -m venv atlas_venv && source atlas_venv/bin/activate
pip install -r requirements.txt
python -m pytest -q                          # the forge refuses to land work unless this passes

python atlas_app.py run --offline --interval 0.5 --duration 90   # free practice run, no API calls

export ANTHROPIC_API_KEY=sk-ant-...
python atlas_app.py run --budget 10 --push   # live: $10/day cap, pushes atlas-forge to GitHub
```

Other commands: `python atlas_app.py status`, `orders`, `add "title" "description"`.

What it produces, all under `atlas_data/`:
- `output/<ID>.md`: what each engineer built
- `research/*.md`: Blood Hound's research notes and sources
- `spend.json`: cost per day per agent
- `atlas.log`: the full log

Review landed work with `git log main..atlas-forge`, and merge it to `main` when you're happy.

Engineer commands are restricted to an allowlist, but an engineer can still run arbitrary
Python inside its worktree. For real isolation, run the forge in a container or VM.

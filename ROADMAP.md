# ATLAS Roadmap

ATLAS is one person's AI: a real-time entity for home, life and family that lives in
wearables today and a robot body later. It grows by building itself: agents research,
plan, code, test and land improvements around the clock.

## How work flows

- **The Forge** (`atlas_app.py run`) runs on the home Ubuntu machine. Blood Hound researches
  the live web and writes work orders, the Director assigns them, and engineers build each
  one in its own git worktree. Work merges into the `atlas-forge` branch only when the full
  test suite passes. With `--push`, `atlas-forge` is pushed to GitHub.
- **8-hour check-ins** (Claude Code, scheduled): review what landed on `atlas-forge`, build the
  next roadmap item directly, keep the tests green, and write a report to `reports/`.
  Anything needing the owner's decision goes out as a multiple-choice question.
- **main** changes only through reviewed promotion from `atlas-forge`. Nothing writes to main
  unattended.

## Phases

### 1. Forge foundations — done
- [x] Research → work order → assign → build → test → merge loop
- [x] Engineers with file and command tools in isolated worktrees
- [x] Test-gated landing; struggles escalate to Blood Hound; orders fail after 3 tries
- [x] Daily spend cap, prompt caching, refusal fallback, live web search
- [x] Offline mode and an end-to-end test of the whole loop

### 2. Forge hardening
- [ ] Run as a systemd service on Ubuntu with automatic restart and log rotation
- [ ] Container isolation for engineer commands
- [ ] Per-order cost cap and turn budget reporting
- [ ] Research dedupe: remember what was already researched
- [ ] Promotion report: a summary of `atlas-forge` vs `main` for review

### 3. ATLAS core: the brain you talk to
- [ ] Conversation interface: talking to ATLAS talks to the brain, which can query and steer the forge
- [ ] Long-term memory (facts, people, preferences, history) with retrieval
- [ ] Model router: Claude for hard work, local models (Ollama / llama.cpp) for cheap or private work
- [ ] Tool registry the brain and the agents share

### 4. Self-extension
- [ ] The forge creates new agents, skills and tools for itself
- [ ] Evaluation harness that measures whether ATLAS got better
- [ ] Improvement loops that propose new loops and automations

### 5. Native models
- [ ] Capture training data from ATLAS's own work and conversations (with consent rules)
- [ ] Local fine-tuning pipeline (LoRA) and evaluation against the harness
- [ ] Promote native models into the router when they win

### 6. Embodiment
- [ ] Voice in and out on phone and wearables, low latency
- [ ] Home and device integrations
- [ ] Real-time presence: ATLAS notices, remembers and acts across the day

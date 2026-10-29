"""
FORGE ENGINEERS — ATLAS Implementation Agents

Each engineer takes one work order at a time, works in its own git worktree
with file and command tools, and only finishes when the full test suite passes.
Work that passes is merged into the integration branch; anything else becomes
a struggle that the Director escalates to Blood Hound.
"""
import logging
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import WorkOrder, Status
from .tracker import WorkOrderTracker
from .workspace import Forge, Workspace, run_tests

log = logging.getLogger("ENGINEER")

MAX_TURNS = 60

TOOLS = [
    {"name": "list_files",
     "description": "List files under a directory of your workspace (default: the repository root).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                      "additionalProperties": False}},
    {"name": "read_file",
     "description": "Read a text file from your workspace.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                      "required": ["path"], "additionalProperties": False}},
    {"name": "write_file",
     "description": "Create or overwrite a file in your workspace with the full content given.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"], "additionalProperties": False}},
    {"name": "edit_file",
     "description": "Replace one exact occurrence of old_text with new_text. old_text must match exactly once.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"}, "old_text": {"type": "string"},
                                     "new_text": {"type": "string"}},
                      "required": ["path", "old_text", "new_text"], "additionalProperties": False}},
    {"name": "run",
     "description": ("Run one command in the workspace root. Allowed programs: python, python3, pytest, "
                     "ls, cat, head, tail, grep, find, wc, and read-only git (status, diff, log, show). "
                     "No shell features such as pipes or redirects. 300 second timeout."),
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}},
                      "required": ["command"], "additionalProperties": False}},
    {"name": "finish",
     "description": ("Report the outcome of this work order. COMPLETE runs the full test suite; if it "
                     "fails you get the output and keep working. NEEDS_RESEARCH hands the blocker to "
                     "Blood Hound."),
     "input_schema": {"type": "object",
                      "properties": {"status": {"type": "string", "enum": ["COMPLETE", "NEEDS_RESEARCH"]},
                                     "summary": {"type": "string"},
                                     "struggle": {"type": "string"}},
                      "required": ["status", "summary"], "additionalProperties": False}},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Engineer:
    def __init__(self, name: str, tracker: WorkOrderTracker, client, forge: Forge,
                 specialties: list = None, model: str = "claude-opus-5-5",
                 output_dir: Path = Path("atlas_data/output"), poll: float = 2.0):
        self.name = name
        self.tracker = tracker
        self.client = client
        self.forge = forge
        self.model = model
        self.specialties = specialties or ["general"]
        self.output_dir = Path(output_dir)
        self.poll = poll
        self.completed = 0
        self.current_work_order: Optional[str] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._system = f"""You are {name}, an ATLAS forge engineer. Specialties: {', '.join(self.specialties)}.

ATLAS is a personal AI system that improves itself: Blood Hound researches and writes
work orders, the Forge Director assigns them, and engineers like you implement them.

You work inside a git worktree of the ATLAS repository: your own isolated copy. Your
tools are list_files, read_file, write_file, edit_file, run and finish.

How to work:
- Read the relevant code before changing it.
- Finish the whole job: the code change plus pytest tests under tests/ that prove it works.
- Run the tests yourself with run("python -m pytest -q") as you go.
- When the work is done, call finish with status COMPLETE. The forge then runs the full
  test suite. If it fails you get the output and keep working. Your work is merged only
  when every test passes.
- If something outside this repository blocks you (a missing package, credentials,
  hardware, or an unclear spec), call finish with NEEDS_RESEARCH and say exactly what
  is needed. Don't fake a solution or leave placeholder code.
- Tests must not touch the network or the Anthropic API. Use atlas.llm.OfflineClient
  for anything that needs a model.
- Never weaken, skip or delete existing tests to get them passing."""

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name=self.name)
        self._thread.start()
        log.info(f"[{self.name}] Ready | Specialties: {self.specialties}")

    def stop(self):
        self._running = False

    def _prompt(self, wo: WorkOrder) -> str:
        context = ""
        if wo.struggles:
            context += "\nEarlier attempts got stuck on:\n" + "\n".join(f"  - {s}" for s in wo.struggles)
        fixes = [f for f in self.tracker.children(wo.id) if f.status == Status.COMPLETE]
        if fixes:
            context += "\nResearch from Blood Hound (already merged; build on it):\n" + "\n".join(
                f"  [{f.id}] {f.title}\n{f.result}" for f in fixes)
        return (f"WORK ORDER\nID: {wo.id}\nTitle: {wo.title}\nPriority: {wo.priority.name}\n"
                f"Tags: {wo.tags}\n\nDescription:\n{wo.description}\n{context}")

    def execute(self, wo: WorkOrder, ws: Workspace) -> dict:
        """Run the tool loop until the engineer finishes. Returns {status, summary, struggle}."""
        messages = [{"role": "user", "content": self._prompt(wo)}]
        for _ in range(MAX_TURNS):
            resp = self.client.create(model=self.model, max_tokens=16000, system=self._system,
                                      messages=messages, tools=TOOLS, effort="high")
            messages.append({"role": "assistant", "content": resp.content})
            calls = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            if not calls:
                nudge = ("Continue." if resp.stop_reason == "max_tokens"
                         else "Keep working with your tools, then call finish.")
                messages.append({"role": "user", "content": nudge})
                continue

            results, outcome = [], None
            for call in calls:
                if call.name == "finish":
                    text, is_error, outcome = self._finish(ws, call.input)
                else:
                    text, is_error = ws.call(call.name, call.input)
                results.append({"type": "tool_result", "tool_use_id": call.id,
                                "content": text, "is_error": is_error})
            if outcome:
                return outcome
            messages.append({"role": "user", "content": results})

        return {"status": "NEEDS_RESEARCH", "summary": "",
                "struggle": f"Ran out of turns ({MAX_TURNS}) before finishing"}

    def _finish(self, ws: Workspace, args: dict):
        status = args.get("status")
        if status == "NEEDS_RESEARCH":
            outcome = {"status": status, "summary": args.get("summary", ""),
                       "struggle": args.get("struggle") or args.get("summary") or "Unspecified"}
            return "Escalating to Blood Hound.", False, outcome
        ok, output = run_tests(ws.path)
        if not ok:
            log.info(f"[{self.name}] [{ws.wo_id}] test suite failed; engineer keeps working")
            return f"The test suite failed. Fix it, then call finish again.\n{output}", True, None
        return "All tests pass.", False, {"status": "COMPLETE", "summary": args.get("summary", "")}

    def _work(self, wo: WorkOrder):
        log.info(f"[{self.name}] Working on [{wo.id}] {wo.title}")
        try:
            ws = self.forge.open(wo.id)
            outcome = self.execute(wo, ws)
            if outcome["status"] == "COMPLETE":
                landed, info = self.forge.land(ws, wo.title)
                if landed:
                    self.forge.close(ws)
                    wo.status = Status.COMPLETE
                    wo.result = f"{outcome['summary']}\n\nMerged into {self.forge.branch} at {info}"
                    wo.completed_at = _now()
                    self.tracker.save(wo)
                    self.completed += 1
                    path = self._write_output(wo)
                    log.info(f"[{self.name}] ✓ LANDED [{wo.id}] {wo.title} @ {info} → {path}")
                    return
                self.forge.close(ws)
                outcome = {"struggle": f"Landing failed: {info}"}
            struggle = outcome["struggle"]
        except Exception as e:
            struggle = f"{type(e).__name__}: {e}"

        wo.struggles.append(struggle[:4000])
        wo.status = Status.NEEDS_RESEARCH
        self.tracker.save(wo)
        log.warning(f"[{self.name}] ⚠ STRUGGLE [{wo.id}]: {struggle[:150]}")

    def _write_output(self, wo: WorkOrder) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{wo.id}.md"
        path.write_text(
            f"# [{wo.id}] {wo.title}\n\n"
            f"Engineer: {wo.assigned_to}  \nCompleted: {wo.completed_at}\n\n"
            f"## Spec\n\n{wo.description}\n\n## Result\n\n{wo.result}\n"
        )
        return path

    def _loop(self):
        while self._running:
            try:
                mine = [wo for wo in self.tracker.by_status(Status.IN_PROGRESS)
                        if wo.assigned_to == self.name]
                if mine:
                    self.current_work_order = mine[0].id
                    try:
                        self._work(mine[0])
                    finally:
                        self.current_work_order = None
                    continue
            except Exception as e:
                log.error(f"[{self.name}] Loop error: {e}")
            time.sleep(self.poll)

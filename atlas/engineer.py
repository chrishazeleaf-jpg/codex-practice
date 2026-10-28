"""
FORGE ENGINEERS — ATLAS Implementation Agents

Rules:
  1. No half-finished work. Ever.
  2. Report struggles IMMEDIATELY — do not grind silently.
  3. One work order at a time to completion.
"""
import logging
import re
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .llm import text_of
from .models import WorkOrder, Status
from .tracker import WorkOrderTracker

log = logging.getLogger("ENGINEER")

OUTPUT_DIR = Path("atlas_data/output")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_report(text: str) -> dict:
    """Parse the STATUS/STRUGGLE/RESULT block. Plain text survives code output where JSON breaks."""
    status = re.search(r"^STATUS:\s*(\w+)", text, re.M)
    struggle = re.search(r"^STRUGGLE:[ \t]*(.*)$", text, re.M)
    result = re.search(r"^RESULT:[ \t]*\n?(.*)", text, re.M | re.S)
    if not status:
        return {"status": "NEEDS_RESEARCH", "result": "",
                "struggle": "Engineer response missing STATUS line"}
    return {
        "status": status.group(1).upper(),
        "struggle": struggle.group(1).strip() if struggle else "",
        "result": result.group(1).strip() if result else "",
    }


class Engineer:
    def __init__(self, name: str, tracker: WorkOrderTracker, client,
                 specialties: list = None, model: str = "claude-sonnet-4-6"):
        self.name = name
        self.tracker = tracker
        self.client = client
        self.model = model
        self.specialties = specialties or ["general"]
        self.completed = 0
        self.current_work_order: Optional[str] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._system = f"""You are {name}, an ATLAS engineer.
Specialties: {', '.join(self.specialties)}

PRIME DIRECTIVE: Complete every work order FULLY. No half-finished implementations.

When you receive a work order:
  1. Understand the full requirements
  2. Design the complete solution
  3. Implement every part of it
  4. If you hit an obstacle you cannot solve alone, report NEEDS_RESEARCH immediately
  5. Never silently struggle

Reply in exactly this format:
STATUS: COMPLETE or NEEDS_RESEARCH
STRUGGLE: <one line; empty when COMPLETE>
RESULT:
<full implementation, code and explanation>

No placeholder code. No TODO comments. Ship it done."""

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name=self.name)
        self._thread.start()
        log.info(f"[{self.name}] Ready | Specialties: {self.specialties}")

    def stop(self):
        self._running = False

    def execute(self, wo: WorkOrder) -> dict:
        self.current_work_order = wo.id
        log.info(f"[{self.name}] Working on [{wo.id}] {wo.title}")

        context = ""
        if wo.struggles:
            context += "\nPrevious struggles:\n" + "\n".join(f"  - {s}" for s in wo.struggles)
        fixes = [f for f in self.tracker.children(wo.id) if f.status == Status.COMPLETE]
        if fixes:
            context += "\nResearch from Blood Hound (apply this):\n" + "\n".join(
                f"  [{f.id}] {f.title}\n{f.result}" for f in fixes)

        prompt = f"""WORK ORDER
ID: {wo.id}
Title: {wo.title}
Priority: {wo.priority.name}
Tags: {wo.tags}

Description:
{wo.description}
{context}"""

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                system=self._system,
                messages=[{"role": "user", "content": prompt}]
            )
            return parse_report(text_of(resp))
        except Exception as e:
            return {"status": "NEEDS_RESEARCH", "result": "",
                    "struggle": f"Engineer exception: {e}"}
        finally:
            self.current_work_order = None

    def _write_output(self, wo: WorkOrder):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUTPUT_DIR / f"{wo.id}.md"
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
                    wo = mine[0]
                    report = self.execute(wo)
                    if report["status"] == "COMPLETE":
                        wo.status = Status.COMPLETE
                        wo.result = report["result"]
                        wo.completed_at = _now()
                        self.tracker.save(wo)
                        self.completed += 1
                        path = self._write_output(wo)
                        log.info(f"[{self.name}] ✓ COMPLETE [{wo.id}] {wo.title} → {path}")
                    else:
                        wo.struggles.append(report["struggle"] or "Unspecified struggle")
                        wo.status = Status.NEEDS_RESEARCH
                        self.tracker.save(wo)
                        log.warning(f"[{self.name}] ⚠ STRUGGLE [{wo.id}]: {wo.struggles[-1][:100]}")
                    continue
            except Exception as e:
                log.error(f"[{self.name}] Loop error: {e}")
            time.sleep(2)

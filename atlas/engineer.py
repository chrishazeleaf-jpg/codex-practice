"""
FORGE ENGINEERS — ATLAS Implementation Agents

Rules:
  1. No half-finished work. Ever.
  2. Report struggles IMMEDIATELY — do not grind silently.
  3. One work order at a time to completion.
"""
import json
import logging
import time
import threading
from datetime import datetime, timezone
from typing import Optional

import anthropic

from .models import WorkOrder, Status
from .tracker import WorkOrderTracker

log = logging.getLogger("ENGINEER")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_json(text: str) -> str:
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text.strip()


class Engineer:
    def __init__(self, name: str, tracker: WorkOrderTracker, api_key: str,
                 specialties: list = None, model: str = "claude-sonnet-4-6"):
        self.name = name
        self.tracker = tracker
        self.client = anthropic.Anthropic(api_key=api_key)
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
  4. If you hit an obstacle you cannot solve alone → report it immediately as NEEDS_RESEARCH
  5. Never silently struggle — that wastes everyone's time

Your output is always JSON:
{{
  "status": "COMPLETE" | "NEEDS_RESEARCH",
  "result": "full implementation / code / detailed outcome — be thorough",
  "struggle": "if NEEDS_RESEARCH: exact description of what is blocking you"
}}

You are building ATLAS — an autonomous AI system. Your work directly improves it.
Make it count. No placeholder code. No TODO comments. Ship it done."""

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=self.name
        )
        self._thread.start()
        log.info(f"[{self.name}] Ready | Specialties: {self.specialties}")

    def stop(self):
        self._running = False

    def execute(self, wo: WorkOrder) -> dict:
        self.current_work_order = wo.id
        log.info(f"[{self.name}] Working on [{wo.id}] {wo.title}")

        struggle_ctx = ""
        if wo.struggles:
            struggle_ctx = f"\nPrevious struggles (learn from these):\n" + \
                           "\n".join(f"  - {s}" for s in wo.struggles)

        prompt = f"""WORK ORDER
ID: {wo.id}
Title: {wo.title}
Priority: {wo.priority.name}
Tags: {wo.tags}

Description:
{wo.description}
{struggle_ctx}

Implement this completely. Return JSON only."""

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self._system,
                messages=[{"role": "user", "content": prompt}]
            )
            text = _extract_json(resp.content[0].text)
            result = json.loads(text)
            self.current_work_order = None
            return result

        except Exception as e:
            self.current_work_order = None
            return {
                "status": "NEEDS_RESEARCH",
                "result": "",
                "struggle": f"Engineer exception: {e}"
            }

    def _loop(self):
        while self._running:
            try:
                in_progress = self.tracker.by_status(Status.IN_PROGRESS)
                my_work = [wo for wo in in_progress if wo.assigned_to == self.name]

                if my_work:
                    wo = my_work[0]
                    result = self.execute(wo)

                    if result.get("status") == "COMPLETE":
                        wo.status = Status.COMPLETE
                        wo.result = result.get("result", "")
                        wo.completed_at = _now()
                        self.tracker.save(wo)
                        self.completed += 1
                        log.info(f"[{self.name}] ✓ COMPLETE [{wo.id}] {wo.title}")
                    else:
                        struggle = result.get("struggle", "Unknown struggle")
                        wo.struggles.append(struggle)
                        wo.status = Status.NEEDS_RESEARCH
                        self.tracker.save(wo)
                        log.warning(f"[{self.name}] ⚠ STRUGGLE [{wo.id}]: {struggle[:100]}")

            except Exception as e:
                log.error(f"[{self.name}] Loop error: {e}")

            time.sleep(5)

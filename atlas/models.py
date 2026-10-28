from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List
import uuid


class Status(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    NEEDS_RESEARCH = "needs_research"
    FAILED = "failed"


class Priority(Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_id() -> str:
    return uuid.uuid4().hex[:8].upper()


@dataclass
class WorkOrder:
    title: str
    description: str
    created_by: str
    id: str = field(default_factory=_short_id)
    status: Status = Status.PENDING
    priority: Priority = Priority.MEDIUM
    assigned_to: Optional[str] = None
    result: Optional[str] = None
    struggles: List[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

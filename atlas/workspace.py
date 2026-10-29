"""
THE FORGE — where engineers build.

Every work order gets its own git worktree on branch forge/<id>, cut from the
integration branch (atlas-forge). Engineers can only touch files inside it.
Work lands on atlas-forge only when the full test suite passes both on the
order's branch and again after merging. main is never touched; promoting
atlas-forge to main is a human (or reviewed) step.

These are guardrails against mistakes, not a security sandbox: an engineer can
run arbitrary Python. Run the forge inside a container or VM if that matters.
"""
import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Tuple

log = logging.getLogger("FORGE")

GIT_IDENTITY = ["-c", "user.name=ATLAS Forge", "-c", "user.email=forge@atlas.local"]
MAX_OUTPUT = 20_000
SCRUBBED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
ALLOWED_PROGRAMS = {"python", "python3", "pytest", "ls", "cat", "head", "tail",
                    "grep", "find", "wc", "git"}
READ_ONLY_GIT = {"status", "diff", "log", "show"}
FORBIDDEN_FIND_ARGS = {"-exec", "-execdir", "-delete", "-ok", "-okdir"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else "...[truncated]...\n" + text[-MAX_OUTPUT:]


def git(cwd, *args, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *GIT_IDENTITY, *args], cwd=cwd,
                       capture_output=True, text=True, env=_env())
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return r


def run_tests(cwd, timeout: int = 900) -> Tuple[bool, str]:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
            cwd=cwd, capture_output=True, text=True, timeout=timeout, env=_env())
    except subprocess.TimeoutExpired:
        return False, f"test suite timed out after {timeout}s"
    return r.returncode == 0, _clip(r.stdout + r.stderr)


class Workspace:
    """One work order's worktree, plus the tools an engineer uses inside it."""

    def __init__(self, wo_id: str, path: Path, branch: str):
        self.wo_id = wo_id
        self.path = Path(path).resolve()
        self.branch = branch

    def _resolve(self, rel: str) -> Path:
        p = (self.path / rel).resolve()
        if p != self.path and self.path not in p.parents:
            raise ValueError(f"path escapes the workspace: {rel}")
        if ".git" in p.relative_to(self.path).parts:
            raise ValueError(".git is off limits")
        return p

    def list_files(self, path: str = ".") -> str:
        base = self._resolve(path)
        found = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            found += [str((Path(dirpath) / f).relative_to(self.path)) for f in sorted(filenames)]
            if len(found) >= 2000:
                break
        return "\n".join(found[:2000]) or "(empty)"

    def read_file(self, path: str) -> str:
        return _clip(self._resolve(path).read_text())

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} chars to {path}"

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        p = self._resolve(path)
        text = p.read_text()
        count = text.count(old_text)
        if count != 1:
            raise ValueError(f"old_text found {count} times in {path}; it must match exactly once")
        p.write_text(text.replace(old_text, new_text))
        return f"edited {path}"

    def run(self, command: str) -> str:
        argv = shlex.split(command)
        if not argv or argv[0] not in ALLOWED_PROGRAMS:
            raise ValueError(f"not allowed: {argv[:1]}. Allowed: {sorted(ALLOWED_PROGRAMS)}")
        if argv[0] == "git" and (len(argv) < 2 or argv[1] not in READ_ONLY_GIT):
            raise ValueError(f"only read-only git is allowed: {sorted(READ_ONLY_GIT)}")
        if argv[0] == "find" and FORBIDDEN_FIND_ARGS & set(argv):
            raise ValueError("find may not execute or delete")
        if argv[0] in ("python", "python3"):
            argv[0] = sys.executable
        elif argv[0] == "pytest":
            argv = [sys.executable, "-m", "pytest", *argv[1:]]
        try:
            r = subprocess.run(argv, cwd=self.path, capture_output=True, text=True,
                               timeout=300, env=_env())
        except subprocess.TimeoutExpired:
            return "timed out after 300s"
        return _clip(f"exit code {r.returncode}\n{r.stdout}{r.stderr}")

    def call(self, name: str, args: dict) -> Tuple[str, bool]:
        tool = {"list_files": self.list_files, "read_file": self.read_file,
                "write_file": self.write_file, "edit_file": self.edit_file,
                "run": self.run}.get(name)
        if tool is None:
            return f"unknown tool: {name}", True
        try:
            return tool(**args), False
        except Exception as e:
            return f"{type(e).__name__}: {e}", True


class Forge:
    def __init__(self, repo_root=".", data_dir=None, branch: str = "atlas-forge",
                 push: bool = False):
        self.repo = Path(repo_root).resolve()
        self.branch = branch
        self.push = push
        self.trees = (Path(data_dir) if data_dir else self.repo / "atlas_data").resolve() / "worktrees"
        self.trees.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        git(self.repo, "worktree", "prune")
        if git(self.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
               check=False).returncode:
            git(self.repo, "branch", branch, "HEAD")
            log.info(f"Created integration branch {branch}")
        self.integration = self.trees / "_integration"
        if not self.integration.exists():
            git(self.repo, "worktree", "add", str(self.integration), branch)

    def open(self, wo_id: str) -> Workspace:
        """Reuse an existing worktree so interrupted work resumes; otherwise cut a fresh one."""
        path, branch = self.trees / wo_id, f"forge/{wo_id}"
        with self._lock:
            if path.exists():
                git(path, "add", "-A")
                git(path, "commit", "-q", "-m", "WIP", check=False)
                if not git(path, "merge", "-q", "--no-edit", self.branch, check=False).returncode:
                    return Workspace(wo_id, path, branch)
                git(path, "merge", "--abort", check=False)
                log.warning(f"[{wo_id}] old worktree conflicts with {self.branch}; starting fresh")
                self._remove(path, branch)
            git(self.repo, "worktree", "add", "-B", branch, str(path), self.branch)
            return Workspace(wo_id, path, branch)

    def land(self, ws: Workspace, title: str) -> Tuple[bool, str]:
        """Commit, merge into the integration branch, re-run tests. Returns (landed, sha or reason)."""
        git(ws.path, "add", "-A")
        if git(ws.path, "diff", "--cached", "--quiet", check=False).returncode:
            git(ws.path, "commit", "-q", "-m", f"[{ws.wo_id}] {title}")
        ahead = git(ws.path, "rev-list", "--count", f"{self.branch}..HEAD").stdout.strip()
        if ahead == "0":
            return False, "no changes to land"

        with self._lock:
            r = git(self.integration, "merge", "--no-ff", "-m",
                    f"forge: [{ws.wo_id}] {title}", ws.branch, check=False)
            if r.returncode:
                git(self.integration, "merge", "--abort", check=False)
                return False, f"merge conflict with {self.branch}:\n{(r.stdout + r.stderr)[-1500:]}"
            ok, out = run_tests(self.integration)
            if not ok:
                git(self.integration, "reset", "-q", "--hard", "ORIG_HEAD")
                return False, f"tests failed after merging into {self.branch}:\n{out[-3000:]}"
            sha = git(self.integration, "rev-parse", "--short", "HEAD").stdout.strip()
            if self.push:
                p = git(self.integration, "push", "-q", "origin", self.branch, check=False)
                if p.returncode:
                    log.warning(f"push of {self.branch} failed: {p.stderr.strip()}")
            return True, sha

    def close(self, ws: Workspace):
        with self._lock:
            self._remove(ws.path, ws.branch)

    def _remove(self, path: Path, branch: str):
        git(self.repo, "worktree", "remove", "--force", str(path), check=False)
        shutil.rmtree(path, ignore_errors=True)
        git(self.repo, "worktree", "prune", check=False)
        git(self.repo, "branch", "-D", branch, check=False)

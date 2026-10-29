import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def git_repo(tmp_path):
    """A throwaway repository with one passing test, standing in for ATLAS."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    (repo / "README.md").write_text("demo\n")
    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", *ident, "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", *ident, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo

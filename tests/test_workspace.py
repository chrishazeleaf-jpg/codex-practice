import subprocess

import pytest

from atlas.workspace import Forge


def _show(repo, ref, path):
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


@pytest.fixture
def forge(git_repo, tmp_path):
    return Forge(git_repo, data_dir=tmp_path / "data")


def test_tools_stay_inside_workspace(forge):
    ws = forge.open("WO1")
    assert ws.call("write_file", {"path": "atlas/x.py", "content": "X = 1\n"}) == \
        ("wrote 6 chars to atlas/x.py", False)
    assert ws.call("read_file", {"path": "atlas/x.py"})[0] == "X = 1\n"

    for args in ({"path": "../escape.txt", "content": "no"}, {"path": ".git/config", "content": "no"}):
        text, is_error = ws.call("write_file", args)
        assert is_error, text


def test_edit_file_requires_unique_match(forge):
    ws = forge.open("WO1")
    ws.write_file("a.py", "x = 1\nx = 1\n")
    text, is_error = ws.call("edit_file", {"path": "a.py", "old_text": "x = 1", "new_text": "y"})
    assert is_error and "2 times" in text


def test_run_allowlist(forge):
    ws = forge.open("WO1")
    assert ws.call("run", {"command": "python -c \"print('hi')\""})[0].endswith("hi\n")
    for command in ("rm -rf /", "git push origin main", "find . -delete", "bash -c ls"):
        text, is_error = ws.call("run", {"command": command})
        assert is_error, command


def test_land_merges_passing_work(forge, git_repo):
    ws = forge.open("WO1")
    ws.write_file("feature.py", "VALUE = 42\n")
    landed, sha = forge.land(ws, "add feature")
    assert landed, sha
    forge.close(ws)
    assert _show(git_repo, "atlas-forge", "feature.py") == "VALUE = 42\n"
    assert _show(git_repo, "main", "feature.py") is None


def test_land_rejects_failing_tests(forge, git_repo):
    ws = forge.open("WO2")
    ws.write_file("tests/test_bad.py", "def test_bad():\n    assert False\n")
    landed, reason = forge.land(ws, "break things")
    assert not landed
    assert "tests failed" in reason
    assert _show(git_repo, "atlas-forge", "tests/test_bad.py") is None


def test_land_with_no_changes(forge):
    ws = forge.open("WO3")
    assert forge.land(ws, "nothing") == (False, "no changes to land")


def test_reopen_resumes_existing_work(forge):
    ws = forge.open("WO4")
    ws.write_file("half_done.py", "STEP = 1\n")
    again = forge.open("WO4")
    assert again.read_file("half_done.py") == "STEP = 1\n"

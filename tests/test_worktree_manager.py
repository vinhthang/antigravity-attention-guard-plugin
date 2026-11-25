import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "git-worktree-sandbox"
    / "scripts"
    / "worktree_manager.py"
)


def _init_git_repo(repo_dir: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, check=True)
    (repo_dir / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_dir, check=True, capture_output=True)


def _run_wm(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )


def test_repo_flag_after_subcommand_lifecycle(tmp_path: Path):
    repo = tmp_path / "repo_after"
    repo.mkdir()
    _init_git_repo(repo)
    outside = tmp_path / "outside"
    outside.mkdir()

    c = _run_wm("create", "wt1", "--repo", str(repo), cwd=outside)
    assert c.returncode == 0, f"stderr: {c.stderr}"
    assert "CREATED_WORKTREE:" in c.stdout

    lst = _run_wm("list", "--repo", str(repo), cwd=outside)
    assert lst.returncode == 0, f"stderr: {lst.stderr}"
    assert "sandbox/wt1" in lst.stdout

    cl = _run_wm("cleanup", "wt1", "--delete-branch", "--repo", str(repo), cwd=outside)
    assert cl.returncode == 0, f"stderr: {cl.stderr}"
    assert "REMOVED_WORKTREE:" in cl.stdout
    assert "DELETED_BRANCH:" in cl.stdout


def test_repo_flag_before_subcommand_lifecycle(tmp_path: Path):
    repo = tmp_path / "repo_before"
    repo.mkdir()
    _init_git_repo(repo)
    outside = tmp_path / "outside"
    outside.mkdir()

    c = _run_wm("--repo", str(repo), "create", "wt2", cwd=outside)
    assert c.returncode == 0, f"stderr: {c.stderr}"
    assert "CREATED_WORKTREE:" in c.stdout

    lst = _run_wm("--repo", str(repo), "list", cwd=outside)
    assert lst.returncode == 0, f"stderr: {lst.stderr}"
    assert "sandbox/wt2" in lst.stdout

    cl = _run_wm("--repo", str(repo), "cleanup", "wt2", "--delete-branch", cwd=outside)
    assert cl.returncode == 0, f"stderr: {cl.stderr}"


def test_non_git_repo_exits_cleanly(tmp_path: Path):
    non_git = tmp_path / "plain_dir"
    non_git.mkdir()

    lst = _run_wm("list", "--repo", str(non_git), cwd=tmp_path)
    assert lst.returncode == 1
    assert "Not a git repository" in lst.stderr

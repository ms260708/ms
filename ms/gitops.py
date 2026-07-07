"""Thin `git -C <path>` wrappers using subprocess.

All functions are defensive: they return None / a sentinel rather than
raising when the path is missing, not a git repo, the remote is absent,
or the branch is unborn. Callers render `n/a` / `missing` accordingly.
"""
from __future__ import annotations

import re
import subprocess


def _run(path: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", path, *args],
        capture_output=True,
        text=True,
    )


def is_git_repo(path: str) -> bool:
    r = _run(path, "rev-parse", "--is-inside-work-tree")
    return r.returncode == 0 and r.stdout.strip() == "true"


def dirty_count(path: str) -> int | None:
    """Number of non-empty lines from `git status --porcelain`; None if not a repo."""
    r = _run(path, "status", "--porcelain")
    if r.returncode != 0:
        return None
    return sum(1 for line in r.stdout.splitlines() if line.strip())


def current_branch(path: str) -> str | None:
    r = _run(path, "symbolic-ref", "--short", "HEAD")
    if r.returncode == 0:
        return r.stdout.strip()
    return None


def has_remote(path: str, name: str) -> bool:
    r = _run(path, "remote")
    if r.returncode != 0:
        return False
    return name in r.stdout.split()


def remote_url(path: str, name: str) -> str | None:
    r = _run(path, "remote", "get-url", name)
    if r.returncode == 0:
        return r.stdout.strip()
    return None


def ahead_behind(
    path: str, remote: str, branch: str | None = None
) -> tuple[int | None, int | None]:
    """Return (ahead, behind) vs `<remote>/<branch>`.

    Uses `git rev-list --left-right --count <remote>/<branch>...HEAD`:
    left = remote-only (behind), right = HEAD-only (ahead).
    Returns (None, None) on any error (missing remote ref, unborn HEAD, ...).
    """
    if branch is None:
        branch = current_branch(path)
    if not branch:
        return (None, None)
    r = _run(path, "rev-list", "--left-right", "--count", f"{remote}/{branch}...HEAD")
    if r.returncode != 0:
        return (None, None)
    parts = r.stdout.split()
    if len(parts) != 2:
        return (None, None)
    try:
        behind, ahead = int(parts[0]), int(parts[1])
    except ValueError:
        return (None, None)
    return (ahead, behind)


# git@github.com:OWNER/REPO[.git]  or  https://github.com/OWNER/REPO[.git]
_GITHUB_SSH_RE = re.compile(r"git@github\.com:([^/]+)/(.+?)(?:\.git)?$")
_GITHUB_HTTPS_RE = re.compile(r"https?://github\.com/([^/]+)/(.+?)(?:\.git)?$")


def parse_github_owner_repo(url: str | None) -> str | None:
    """Return 'owner/repo' from a GitHub remote URL, else None."""
    if not url:
        return None
    m = _GITHUB_SSH_RE.match(url) or _GITHUB_HTTPS_RE.match(url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return None


def detect_origin(path: str) -> str | None:
    """owner/repo inferred from the origin remote URL, else None."""
    return parse_github_owner_repo(remote_url(path, "origin"))


def add_remote(path: str, name: str, url: str, dry_run: bool = False) -> str:
    """Add <name> remote, or set-url if it already exists. Returns a status string."""
    if has_remote(path, name):
        argv = ["git", "-C", path, "remote", "set-url", name, url]
        action = "set-url"
    else:
        argv = ["git", "-C", path, "remote", "add", name, url]
        action = "add"
    if dry_run:
        return " ".join(argv)
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        return f"FAILED({action}): {r.stderr.strip()[:120]}"
    return f"ok({action})"


def push(path: str, remote: str, ref: str = "HEAD", dry_run: bool = False) -> str:
    """Push <ref> to <remote>. With dry_run, returns the command instead of running it."""
    argv = ["git", "-C", path, "push", remote, ref]
    if dry_run:
        return " ".join(argv)
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        return "FAILED: " + r.stderr.strip()[:140]
    return "ok"


def pull(path: str, remote: str, dry_run: bool = False) -> str:
    """Fast-forward pull of the current branch from <remote>.

    Uses --ff-only so a sync tool never creates surprise merge commits: a
    divergent worktree is reported as FAILED for the user to resolve by hand.
    Returns 'ok', a 'FAILED: ...' message, or the command string on dry_run.
    """
    branch = current_branch(path)
    if not branch:
        return "FAILED: unborn HEAD (no current branch)"
    argv = ["git", "-C", path, "pull", "--ff-only", remote, branch]
    if dry_run:
        return " ".join(argv)
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        msg = (r.stderr.strip() or r.stdout.strip())
        return "FAILED: " + msg[:140]
    return "ok"


def clone(url: str, path: str, dry_run: bool = False) -> str:
    """Clone <url> into <path>. With dry_run, returns the command instead of running it."""
    argv = ["git", "clone", url, path]
    if dry_run:
        return " ".join(argv)
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        return "FAILED: " + r.stderr.strip()[:140]
    return "ok"


def rename_remote(path: str, old: str, new: str) -> str:
    """Rename remote <old> -> <new>. Returns a status string."""
    r = subprocess.run(
        ["git", "-C", path, "remote", "rename", old, new],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return f"FAILED(rename {old}->{new}): " + r.stderr.strip()[:120]
    return f"ok(rename {old}->{new})"


def fetch_remote(path: str, remote: str) -> str:
    """Fetch <remote>. Returns a status string."""
    r = subprocess.run(
        ["git", "-C", path, "fetch", remote],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return f"FAILED(fetch {remote}): " + r.stderr.strip()[:120]
    return f"ok(fetch {remote})"


def checkout_default_branch(path: str) -> str:
    """Ensure the right local branch is checked out after a clone.

    Bare mirrors created via `git init --bare` default HEAD to 'master', so
    cloning from them can leave the worktree on an unborn 'master' even when the
    real default branch is 'main'. Detect origin's advertised default and check
    it out (DWIM creates the local tracking branch).
    """
    subprocess.run(
        ["git", "-C", path, "remote", "set-head", "origin", "-a"],
        capture_output=True,
        text=True,
    )
    r = subprocess.run(
        ["git", "-C", path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
    )
    if r.returncode == 0 and r.stdout.strip():
        branch = r.stdout.strip().rsplit("/", 1)[-1]
        if branch:
            c = subprocess.run(
                ["git", "-C", path, "checkout", "-B", branch, f"origin/{branch}"],
                capture_output=True,
                text=True,
            )
            if c.returncode == 0:
                return f"ok(checkout {branch})"
            return f"FAILED(checkout {branch}): " + c.stderr.strip()[:120]
    return "ok(no default-branch change needed)"

"""Aliyun bare-mirror creation + aliyun remote wiring.

The mirror lives on the VPS at `<ssh_host>:<base_dir>/<name>.git` (a bare repo).
`~/` in base_dir is expanded by the REMOTE shell (kept literal in the ssh command),
so manifests stay portable across machines with different home dirs.

WARNING: ensure_mirror(execute=True) has side effects on the VPS (ssh + git init --bare).
         Always pass dry_run=True for inspection / during build & test.
"""
from __future__ import annotations

import subprocess

from . import gitops


def mirror_remote_url(ssh_host: str, base_dir: str, name: str) -> str:
    """scp-like url understood by git: <ssh_host>:<base_dir>/<name>.git"""
    return f"{ssh_host}:{base_dir}/{name}.git"


def mirror_ssh_remote(ssh_host: str, base_dir: str, name: str) -> str:
    """The remote shell snippet to run on the VPS (handed to ssh as one arg)."""
    return f"mkdir -p {base_dir} && git init --bare {base_dir}/{name}.git"


def mirror_ssh_cmd_str(ssh_host: str, base_dir: str, name: str) -> str:
    """Human-readable ssh command string (quoted for display)."""
    return f'ssh {ssh_host} "{mirror_ssh_remote(ssh_host, base_dir, name)}"'


def ensure_mirror(
    path: str,
    name: str,
    ssh_host: str,
    base_dir: str,
    dry_run: bool = False,
) -> list[str]:
    """Ensure the aliyun bare mirror exists and the local `aliyun` remote points at it.

    Returns a list of human-readable result lines. With dry_run=True nothing runs;
    the exact ssh + git commands that would run are returned instead.
    """
    results: list[str] = []
    remote = mirror_ssh_remote(ssh_host, base_dir, name)
    url = mirror_remote_url(ssh_host, base_dir, name)

    if dry_run:
        results.append(
            " ".join(["ssh", ssh_host, f'"{remote}"'])
        )
        results.append(gitops.add_remote(path, "aliyun", url, dry_run=True))
        return results

    r = subprocess.run(["ssh", ssh_host, remote], capture_output=True, text=True)
    if r.returncode != 0:
        results.append("ssh FAILED: " + r.stderr.strip()[:160])
        return results
    results.append("mirror: created/verified")
    results.append("aliyun remote: " + gitops.add_remote(path, "aliyun", url))
    results.append("aliyun fetch: " + gitops.fetch_remote(path, "aliyun"))
    return results

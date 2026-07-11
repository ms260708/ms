"""Manifest loading, saving, and path helpers.

Reads TOML via stdlib tomllib; writes TOML by generating strings manually
(no runtime dependency). The manifest is a small config file of the form:

    [github]
    default_owner = "licoded"

    [aliyun]
    ssh_host = "aliyun_server"
    base_dir = "~/repos"

    [[repo]]
    name = "cdx"
    path = "~/tmp/cdx"
    github = "licoded/cdx"
    push_policy = "aliyun-only"
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

DEFAULT_GITHUB = {"default_owner": "licoded"}
DEFAULT_ALIYUN = {"ssh_host": "aliyun_server", "base_dir": "~/repos"}

DEFAULT_MANIFEST_TEXT = """\
[github]
default_owner = "licoded"

[aliyun]
ssh_host = "aliyun_server"
base_dir = "~/repos"

# Repos are appended below as [[repo]] blocks by `ms add`.
"""


def manifest_path() -> str:
    """Resolve the manifest path: MS_MANIFEST env or ~/.config/ms/manifest.toml."""
    return os.environ.get("MS_MANIFEST") or os.path.expanduser(
        "~/.config/ms/manifest.toml"
    )


def expand(path: str | None) -> str | None:
    """expanduser a path; None-safe."""
    if path is None:
        return None
    return os.path.expanduser(path)


def shorten_home(path: str) -> str:
    """Convert an absolute path under $HOME to a ~/ form (portable across machines)."""
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def load(path: str | None = None) -> dict:
    """Load and return the manifest as a dict (raises if missing)."""
    path = path or manifest_path()
    with open(path, "rb") as f:
        return tomllib.load(f)


def github_section(data: dict) -> dict:
    """Resolved [github] section (defaults merged with user values)."""
    return {**DEFAULT_GITHUB, **data.get("github", {})}


def aliyun_section(data: dict) -> dict:
    """Resolved [aliyun] section (defaults merged with user values)."""
    return {**DEFAULT_ALIYUN, **data.get("aliyun", {})}


def repos(data: dict) -> list[dict]:
    """List of [[repo]] entries."""
    return data.get("repo", [])


def ensure_default_manifest(path: str | None = None) -> str:
    """Create the manifest (and its parent dir) with defaults if it doesn't exist."""
    path = path or manifest_path()
    if not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as f:
            f.write(DEFAULT_MANIFEST_TEXT)
    return path


def _esc(s: str) -> str:
    """Escape a TOML basic-string value."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def format_repo_block(repo: dict) -> str:
    """Serialize one repo dict as a [[repo]] TOML block (text append-friendly)."""
    lines = ["", "[[repo]]"]
    lines.append(f'name = "{_esc(repo["name"])}"')
    lines.append(f'path = "{_esc(repo["path"])}"')
    if repo.get("github"):
        lines.append(f'github = "{_esc(repo["github"])}"')
    lines.append(f'push_policy = "{_esc(repo["push_policy"])}"')
    return "\n".join(lines) + "\n"


def append_repo(path: str, repo: dict) -> None:
    """Append a single [[repo]] block to the manifest file (preserves existing content)."""
    with open(path, "a") as f:
        f.write(format_repo_block(repo))


def find_repo_by_name(data: dict, name: str) -> dict | None:
    for r in repos(data):
        if r.get("name") == name:
            return r
    return None


def find_repo_by_path(data: dict, exp_path: str) -> dict | None:
    for r in repos(data):
        if expand(r.get("path")) == exp_path:
            return r
    return None


def update_repo_field(
    mpath: str, name: str, updates: dict[str, str | None]
) -> bool:
    """Edit a [[repo]] block in-place by name.

    *updates* maps TOML keys to new values.  A value of ``None`` (or empty
    string) means *delete that key* from the block.  Returns ``True`` if the
    block was found and modified.
    """
    with open(mpath, "r") as f:
        lines = f.readlines()

    # 1. Find all [[repo]] blocks and their ranges.
    blocks: list[tuple[int, int]] = []
    current_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[[repo]]":
            if current_start is not None:
                blocks.append((current_start, i - 1))
            current_start = i
    if current_start is not None:
        blocks.append((current_start, len(lines) - 1))

    # 2. Find the block that contains name = "..."
    target_start = target_end = None
    for start, end in blocks:
        for i in range(start, end + 1):
            stripped = lines[i].strip()
            if stripped.startswith("name = ") and f'"{name}"' in stripped:
                target_start, target_end = start, end
                break
        if target_start is not None:
            break

    if target_start is None:
        return False

    # 3. Apply updates within the block.
    for key, val in updates.items():
        # Find existing key line
        key_line_idx = None
        for i in range(target_start, target_end + 1):
            stripped = lines[i].strip()
            if stripped.startswith(f"{key} = "):
                key_line_idx = i
                break

        if val is None or val == "":
            # Delete the line
            if key_line_idx is not None:
                del lines[key_line_idx]
                target_end -= 1
        else:
            new_line = f'{key} = "{_esc(val)}"\n'
            if key_line_idx is not None:
                lines[key_line_idx] = new_line
            else:
                # Insert after the last line of the block
                lines.insert(target_end + 1, new_line)
                target_end += 1

    with open(mpath, "w") as f:
        f.writelines(lines)
    return True

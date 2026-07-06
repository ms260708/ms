# ms

A personal **multi-repo + dual-remote sync manager**. Each managed git repo gets
two remotes:

- `origin` — GitHub
- `aliyun` — a **bare mirror** on an always-on VPS (`ssh aliyun_server:~/repos/<name>.git`)

A normal `ms push` pushes to **aliyun only** (the fast, always-on backup).
`ms push --backup` also pushes to **origin (GitHub)**. Forks / repos you don't own
get policy `skip` and are never pushed.

Stdlib only (no runtime dependencies). Python 3.11+.

## Install

```bash
cd ~/tmp/ms
uv tool install .
```

Or just run in place without installing:

```bash
python -m ms.cli <command>
```

## Manifest

Auto-created at `~/.config/ms/manifest.toml` on first `ms add` (override the path
with the `MS_MANIFEST` environment variable, handy for tests):

```toml
[github]
default_owner = "licoded"

[aliyun]
ssh_host = "aliyun_server"
base_dir = "~/repos"      # ~ is expanded on the REMOTE shell

[[repo]]
name = "cdx"
path = "~/tmp/cdx"        # ~ is expanduser'd locally before use
github = "licoded/cdx"    # owner/repo; omit if there is no github remote
push_policy = "aliyun-only"   # aliyun-only | both | skip
```

## Commands

| Command | Description |
| --- | --- |
| `ms list` | Print registered repos + aliyun/github config. |
| `ms status` | Per repo: dirty-file count + ahead/behind vs `origin` and `aliyun`. |
| `ms add <path> [--name N] [--policy P] [--no-mirror]` | Register a repo (auto-detects `origin`, infers policy, optionally creates the mirror). |
| `ms mirror [<path>]` | Ensure the aliyun bare mirror exists and `aliyun` remote is set (all repos if no path). |
| `ms push [--backup] [--name N]` | Push `HEAD` to aliyun; `--backup` (or policy `both`) also pushes to origin. `skip` repos are skipped. |
| `ms bootstrap` | Clone repos whose local path is missing (from aliyun mirror, else origin). |
| `ms config` | Print resolved manifest path, ssh_host, base_dir, default_owner, repo count. |

Global / per-command flag `-n` (`--dry-run`): for side-effecting commands, print the
exact `ssh` / `git` commands that would run (and the manifest changes) without
executing anything. Read-only commands ignore it.

## Typical flow on a new machine

```bash
ms add ~/tmp/cdx               # registers + creates the aliyun mirror
ms add ~/tmp/VideoCaptioner    # detected as a fork -> policy=skip
ms status                      # see what's dirty / ahead / behind
ms push                        # fast backup to the VPS
ms push --backup               # also push to GitHub
```

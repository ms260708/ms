"""argparse CLI: subcommand dispatch for `ms`.

Read-only commands: list, status, config (ignore --dry-run).
Side-effecting commands: add (mirror step), mirror, push, pull, bootstrap
(each accepts -n/--dry-run to print exact commands without running them).
"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from . import gitops, manifest, mirror


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ms",
        description="Multi-repo + dual-remote sync manager (GitHub + aliyun bare mirror).",
    )
    p.add_argument("--version", action="version", version=f"ms {__version__}")
    # Global dry-run (usable as `ms --dry-run <cmd>` OR `ms <cmd> --dry-run`).
    # Side-effecting subparsers re-declare it with default=SUPPRESS so they only
    # override when explicitly passed after the subcommand.
    p.add_argument("-n", "--dry-run", action="store_true", default=False)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="list registered repos + aliyun/github config")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("status", help="show dirty + ahead/behind per repo")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("add", help="register a repo")
    sp.add_argument("path")
    sp.add_argument("--name", help="repo name (default: basename of path)")
    sp.add_argument("--policy", choices=["aliyun-only", "both", "skip"])
    sp.add_argument("--no-mirror", action="store_true", help="skip the aliyun mirror step")
    sp.add_argument("-n", "--dry-run", action="store_true", default=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("mirror", help="ensure aliyun bare mirror exists for repo(s)")
    sp.add_argument("path", nargs="?", help="operate on one repo (default: all)")
    sp.add_argument("-n", "--dry-run", action="store_true", default=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_mirror)

    sp = sub.add_parser("push", help="push to aliyun (and origin with --all)")
    sp.add_argument("--all", action="store_true", help="also push to origin (GitHub)")
    sp.add_argument("--name", help="select a single repo by name")
    sp.add_argument("-n", "--dry-run", action="store_true", default=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_push)

    sp = sub.add_parser("pull", help="pull from aliyun (and origin with --backup)")
    sp.add_argument("--backup", action="store_true", help="pull from origin (GitHub) instead of aliyun")
    sp.add_argument("--name", help="select a single repo by name")
    sp.add_argument("-n", "--dry-run", action="store_true", default=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_pull)

    sp = sub.add_parser("bootstrap", help="clone repos whose path is missing")
    sp.add_argument("-n", "--dry-run", action="store_true", default=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_bootstrap)

    sp = sub.add_parser("edit", help="modify a registered repo's settings")
    sp.add_argument("name", help="repo name to edit")
    sp.add_argument("--name", dest="new_name", help="change display name")
    sp.add_argument("--policy", choices=["aliyun-only", "both", "skip"])
    sp.add_argument("--github", help="set github owner/repo (pass '' to clear)")
    sp.add_argument("-n", "--dry-run", action="store_true", default=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_edit)

    sp = sub.add_parser("config", help="print resolved manifest path and config")
    sp.set_defaults(func=cmd_config)

    return p


# --------------------------------------------------------------------------
# helpers


def _load_or_exit() -> tuple[dict, str]:
    mpath = manifest.manifest_path()
    if not os.path.exists(mpath):
        print(
            f"manifest not found: {mpath}\n(run `ms add <path>` to create it).",
            file=sys.stderr,
        )
        sys.exit(2)
    return manifest.load(mpath), mpath


def _fmt_ab(ahead: int | None, behind: int | None) -> str:
    if ahead is None or behind is None:
        return "—"
    if ahead == 0 and behind == 0:
        return "—"
    parts = []
    if ahead:
        parts.append(f"↑{ahead}")
    if behind:
        parts.append(f"↓{behind}")
    return "".join(parts)


def _remote_ab(path: str, remote: str) -> str:
    if not gitops.has_remote(path, remote):
        return "missing"
    ahead, behind = gitops.ahead_behind(path, remote)
    return _fmt_ab(ahead, behind)


# --------------------------------------------------------------------------
# read-only commands


def cmd_list(args) -> int:
    data, mpath = _load_or_exit()
    gh = manifest.github_section(data)
    al = manifest.aliyun_section(data)
    rs = manifest.repos(data)
    print(f"manifest: {mpath}")
    print(f"github default_owner: {gh.get('default_owner')}")
    print(f"aliyun ssh_host={al.get('ssh_host')}  base_dir={al.get('base_dir')}")
    print(f"{len(rs)} repo(s):")
    print(f"{'NAME':<20} {'POLICY':<14} {'GITHUB':<32} PATH")
    for r in rs:
        print(
            f"{str(r.get('name', '')):<20} {str(r.get('push_policy', '')):<14} "
            f"{str(r.get('github') or '-'):<32} {r.get('path', '')}"
        )
    return 0


def cmd_status(args) -> int:
    data, _ = _load_or_exit()
    rs = manifest.repos(data)
    rows: list[tuple] = []
    for r in rs:
        name = str(r.get("name", "?"))
        policy = str(r.get("push_policy", "?"))
        exp = manifest.expand(r.get("path"))
        if not exp or not os.path.isdir(exp):
            rows.append((name, policy, "missing", "missing", "missing"))
            continue
        dirty = gitops.dirty_count(exp)
        dirty_s = "n/a" if dirty is None else str(dirty)
        rows.append(
            (name, policy, dirty_s, _remote_ab(exp, "origin"), _remote_ab(exp, "aliyun"))
        )
    header = ("NAME", "POLICY", "DIRTY", "GITHUB", "ALIYUN")
    table = [header, *[[str(c) for c in row] for row in rows]]
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    for row in table:
        print(fmt.format(*row))
    return 0


def cmd_config(args) -> int:
    mpath = manifest.manifest_path()
    exists = os.path.exists(mpath)
    data = manifest.load(mpath) if exists else {}
    gh = manifest.github_section(data)
    al = manifest.aliyun_section(data)
    print(f"manifest_path: {mpath} (exists={exists})")
    print(f"ssh_host: {al.get('ssh_host')}")
    print(f"base_dir: {al.get('base_dir')}")
    print(f"default_owner: {gh.get('default_owner')}")
    print(f"repo_count: {len(manifest.repos(data))}")
    return 0


# --------------------------------------------------------------------------
# side-effecting commands


def cmd_add(args) -> int:
    mpath = manifest.manifest_path()
    if not os.path.exists(mpath):
        manifest.ensure_default_manifest(mpath)
        print(f"created manifest: {mpath}")
    data = manifest.load(mpath)
    gh = manifest.github_section(data)
    al = manifest.aliyun_section(data)

    raw_path = args.path
    exp = manifest.expand(raw_path)
    name = args.name or os.path.basename(os.path.normpath(exp or raw_path))

    if manifest.find_repo_by_name(data, name):
        print(f"repo '{name}' already in manifest", file=sys.stderr)
        return 1

    github = None
    if exp and os.path.isdir(exp):
        github = gitops.detect_origin(exp)

    policy = args.policy
    if policy is None:
        if github is None:
            policy = "aliyun-only"
        elif github.split("/", 1)[0] == gh.get("default_owner"):
            policy = "aliyun-only"
        else:
            policy = "skip"

    repo = {
        "name": name,
        "id": name,  # id defaults to name for new repos
        "path": manifest.shorten_home(exp or raw_path),
        "github": github,
        "push_policy": policy,
    }

    dry = args.dry_run
    if not args.no_mirror:
        if not exp or not os.path.isdir(exp):
            print(f"warning: path not found, cannot mirror: {exp}", file=sys.stderr)
        else:
            for line in mirror.ensure_mirror(
                exp, manifest.repo_id(repo), al.get("ssh_host"), al.get("base_dir"), dry_run=dry
            ):
                print("  " + line)

    block = manifest.format_repo_block(repo)
    if dry:
        print(f"[dry-run] would append to {mpath}:")
        print(block, end="")
    else:
        manifest.append_repo(mpath, repo)
        print(f"appended [[repo]] {name} to {mpath}")
    print(
        f"  name={name} path={repo['path']} github={github or '-'} policy={policy}"
    )
    return 0


def cmd_edit(args) -> int:
    data, mpath = _load_or_exit()
    repo = manifest.find_repo_by_name(data, args.name)
    if not repo:
        print(f"no repo named '{args.name}'", file=sys.stderr)
        return 1

    updates: dict[str, str | None] = {}
    if args.new_name is not None:
        updates["name"] = args.new_name
    if args.policy is not None:
        updates["push_policy"] = args.policy
    if args.github is not None:
        updates["github"] = args.github or None  # "" → None (clear)

    if not updates:
        print("nothing to change", file=sys.stderr)
        return 1

    for k, v in updates.items():
        print(f"  {k}: {repo.get(k, '(absent)')} → {v or '(removed)'}")

    if args.dry_run:
        print(f"[dry-run] would update {mpath}")
    else:
        manifest.update_repo_field(mpath, args.name, updates)
        print(f"updated [[repo]] {args.name} in {mpath}")
    return 0


def cmd_mirror(args) -> int:
    data, _ = _load_or_exit()
    al = manifest.aliyun_section(data)
    rs = manifest.repos(data)
    if args.path:
        exp_in = manifest.expand(args.path)
        rs = [r for r in rs if manifest.expand(r.get("path")) == exp_in]
        if not rs:
            print(f"no registered repo matches path: {args.path}", file=sys.stderr)
            return 1
    for r in rs:
        rid = manifest.repo_id(r)
        exp = manifest.expand(r.get("path"))
        print(f"== {rid} ({exp})")
        if not exp or not os.path.isdir(exp):
            print("  path missing - skip")
            continue
        for line in mirror.ensure_mirror(
            exp, rid, al.get("ssh_host"), al.get("base_dir"), dry_run=args.dry_run
        ):
            print("  " + line)
    return 0


def cmd_push(args) -> int:
    data, _ = _load_or_exit()
    rs = manifest.repos(data)
    if args.name:
        rs = [r for r in rs if r.get("name") == args.name]
        if not rs:
            print(f"no repo named '{args.name}'", file=sys.stderr)
            return 1
    label = "dry-run" if args.dry_run else "push"
    for r in rs:
        name = str(r.get("name", "?"))
        policy = str(r.get("push_policy", "?"))
        exp = manifest.expand(r.get("path"))
        if policy == "skip":
            print(f"{name}: skipped (policy=skip)")
            continue
        if not exp or not os.path.isdir(exp):
            print(f"{name}: skipped (path missing)")
            continue
        parts = [f"aliyun: {gitops.push(exp, 'aliyun', 'HEAD', dry_run=args.dry_run)}"]
        if args.all or policy == "both":
            parts.append(
                f"origin: {gitops.push(exp, 'origin', 'HEAD', dry_run=args.dry_run)}"
            )
        print(f"{name}: [{label}] " + ", ".join(parts))
    return 0


def cmd_pull(args) -> int:
    data, _ = _load_or_exit()
    rs = manifest.repos(data)
    if args.name:
        rs = [r for r in rs if r.get("name") == args.name]
        if not rs:
            print(f"no repo named '{args.name}'", file=sys.stderr)
            return 1
    label = "dry-run" if args.dry_run else "pull"
    for r in rs:
        name = str(r.get("name", "?"))
        policy = str(r.get("push_policy", "?"))
        exp = manifest.expand(r.get("path"))
        if policy == "skip":
            print(f"{name}: skipped (policy=skip)")
            continue
        if not exp or not os.path.isdir(exp):
            print(f"{name}: skipped (path missing)")
            continue
        remote = "origin" if args.backup else "aliyun"
        if not gitops.has_remote(exp, remote):
            print(f"{name}: skipped (remote '{remote}' missing)")
            continue
        print(f"{name}: [{label}] {remote}: {gitops.pull(exp, remote, dry_run=args.dry_run)}")
    return 0


def cmd_bootstrap(args) -> int:
    data, mpath = _load_or_exit()
    al = manifest.aliyun_section(data)
    rs = manifest.repos(data)
    for r in rs:
        name = str(r.get("name", "?"))
        rid = manifest.repo_id(r)
        policy = str(r.get("push_policy", "?"))
        exp = manifest.expand(r.get("path"))

        # Backfill id if missing (backward compatibility)
        if not r.get("id") and not args.dry_run:
            manifest.update_repo_field(mpath, name, {"id": name})
            print(f"{name}: backfilled id={name}")

        if exp and os.path.isdir(exp) and gitops.is_git_repo(exp):
            print(f"{name}: present ({exp})")
            continue
        if exp and os.path.isdir(exp) and not gitops.is_git_repo(exp):
            print(f"{name}: path exists but is not a git repo - skip")
            continue
        url, src = None, None
        if policy != "skip" and al.get("ssh_host"):
            url = mirror.mirror_remote_url(
                al["ssh_host"], al.get("base_dir", "~/repos"), rid
            )
            src = "aliyun"
        elif r.get("github"):
            url = f"git@github.com:{r['github']}.git"
            src = "origin"
        if not url:
            print(f"{name}: no clone source (no github/aliyun) - skip")
            continue
        if args.dry_run:
            print(f"{name}: [{src}] [dry-run] git clone {url} {exp}")
            continue
        print(f"{name}: cloning from {src} ...")
        cres = gitops.clone(url, exp)
        print("  clone: " + cres)
        if not cres.startswith("ok"):
            continue
        # Normalize remotes so origin=GitHub, aliyun=mirror.
        # (git clone set origin=<source url>; fix it to the canonical layout.)
        gh = r.get("github")
        if src == "aliyun":
            print("  " + gitops.rename_remote(exp, "origin", "aliyun"))
            if gh:
                print("  " + gitops.add_remote(exp, "origin", f"git@github.com:{gh}.git"))
                print("  " + gitops.fetch_remote(exp, "origin"))
        else:  # cloned from origin (github)
            if al.get("ssh_host"):
                aurl = mirror.mirror_remote_url(
                    al["ssh_host"], al.get("base_dir", "~/repos"), rid
                )
                print("  " + gitops.add_remote(exp, "aliyun", aurl))
                print("  " + gitops.fetch_remote(exp, "aliyun"))
        print("  " + gitops.checkout_default_branch(exp))
    return 0


if __name__ == "__main__":
    sys.exit(main())

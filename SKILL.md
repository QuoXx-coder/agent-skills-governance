---
name: agent-skills-governance
description: Use when a user has Skills across two or more AI agents, wants to initialize or inspect a shared Skill source, reconcile drift or broken entries, safely sync approved Skills, or evaluate a newly installed agent before it joins shared Skill governance.
---

# Agent Skills Governance

Treat a shared Skill as an asset with one authority, not a file copied between agents. The public source is normally `~/.agents/skills` (Windows: `%USERPROFILE%\.agents\skills`). Discovery and diagnosis are read-only; no finding authorizes a write.

## New-user route

When the user provides this Skill's path or URL, install it using the current host's native mechanism. Then, for “初始化 / 检查我的 Skill 治理”, read [first-time onboarding](references/onboarding.md) and run the read-only `doctor` command. Present its state card before asking for any registration, link, copy, migration, or cleanup approval.

Use `uv`'s Python if available; otherwise use Python 3.9+ (`python3` on macOS/Linux, `py -3` on Windows). Do not install a runtime without consent.

## Operating model

- `direct`: the host declares `direct_source_root`; it must be the public root. Do not create a duplicate host directory.
- `symlink`: the host entry points to the public source. Prefer it when the host and platform support directory links.
- `managed_copy`: only for hosts that cannot use links. Copies carry `.agent-skill-source.json` and update atomically.
- Marketplace, bundled, cache, and project-only Skills are never adopted automatically. One same-named Skill in one host has one authority. A host-owned authority needs a structured exception with its source and reason.

For the user-facing mental model and conflict decisions, read [the handbook](references/handbook.md). For the Profile format, read [profiles/README.md](profiles/README.md) only when evaluating a new host.

## Commands

```bash
# First look: read-only status card with candidates and runtime evidence
python3 scripts/governance.py doctor

# Detailed read-only operations
python3 scripts/governance.py discover
python3 scripts/governance.py audit --strict --format json

# Preview; add --apply only after the user confirms exact entries
python3 scripts/governance.py sync
python3 scripts/governance.py sync --apply
```

New installations use two local files: `~/.agents/governance.json` (hosts, plugin records, canonical root) and `~/.agents/skills.lock.json` (generated Skill hashes). Pass both with `--governance` and `--lock`. The older `~/.agents/skills-registry.json` remains read-compatible; discovery must not overwrite it.

Before `sync --apply`, the core rejects unsafe names, missing `SKILL.md`, invalid frontmatter, source/hash drift, unknown targets, and an invalid direct source. It never replaces an unknown real directory. Cleaning, registration, migration, or a Profile update still needs explicit confirmation.

## Verification

After an approved change, run the smallest relevant test, then `audit --strict`. A valid result has no hash drift, no broken entry, and no unapproved duplicate authority. Do not claim a host is managed merely because an app name or a folder was discovered.

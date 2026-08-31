# Agent Skills Governance

Give every shared Skill one home, then let each verified agent use a managed entry. This package is for people using two or more AI agents and who need to avoid copied, drifting, or conflicting Skills.

## First use

Give this folder or repository URL to your current AI agent and say:

> Install this Skill, then initialize my Skill governance.

The agent should use its native installation mechanism, run a read-only diagnosis, and show a plan before creating a public directory, registering a host, creating links, or cleaning files.

```bash
# macOS / Linux
python3 scripts/governance.py doctor

# Windows PowerShell
py -3 scripts\governance.py doctor --platform windows
```

The core needs Python 3.9+ and has no third-party runtime dependency. Prefer `uv` when present. `doctor` reports the Python runtime, managed state, errors/warnings, and unverified host candidates without making filesystem changes.

## Local state

For a new installation, keep machine-specific state under `~/.agents/` (Windows: `%USERPROFILE%\.agents\`):

```text
.agents/
├── skills/              public shared source
├── governance.json      schema v2: hosts, plugins, canonical source root
├── skills.lock.json     schema v1: generated Skill names and hashes
└── profiles/            user-confirmed Host Profile updates
```

Start from [governance.json](templates/governance.json) and [skills.lock.json](templates/skills.lock.json). The old [portable-registry.json](templates/portable-registry.json) remains only for legacy read compatibility; it is not the starting point for a new machine.

## Commands

| Command | Effect |
| --- | --- |
| `doctor` | Read-only state card: audit, candidates, and runtime. |
| `discover` | Read-only candidate discovery; a candidate is never an approved host. |
| `audit` | Read-only check of hashes, frontmatter, entries, residuals, and conflicts. |
| `sync` | Dry-run entry plan. `--apply` writes only after preflight succeeds. |
| `hash` | Print the content hash for a source directory. |

Use `--format json` with `doctor` or `audit` for stable machine output. A v2 state must pass both `--governance ~/.agents/governance.json` and `--lock ~/.agents/skills.lock.json`; the pair is intentionally required.

## Safety properties

- `sync --apply` refuses unsafe Skill names, missing `SKILL.md`, invalid frontmatter, hash drift, unknown target hosts, and invalid direct sources.
- A `direct` host must name the public root with `direct_source_root`.
- `symlink` is preferred; Windows falls back to `managed_copy` only after link capability has been checked.
- Managed-copy updates stage a random temporary directory, validate it, and roll back a managed old copy on failure. Unknown directories are never replaced.
- Marketplace and built-in Skills remain host-owned. Do not synchronize over a same-named host capability; record a structured exception instead.

Read [the handbook](references/handbook.md) for the decision model. Built-in and user-supplied discovery evidence is documented in [profiles/README.md](profiles/README.md); `~/.agents/profiles/` loads automatically and `--profiles-dir` adds an extra review directory.

## Tests

```bash
python3 tests/portable_governance_test.py
```

The test suite covers Linux/macOS-style links, Windows managed copies, v2 direct readers, Profile-based candidate discovery, and preflight rejection of unsafe writes.

## License

[MIT](LICENSE)

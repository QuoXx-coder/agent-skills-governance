# First-time onboarding

When a user gives an agent this Skill folder or repository URL, the agent should first install it using that host's native Skill mechanism. If the host cannot install from a path or URL, explain the shortest official manual step; do not copy the package into unrelated host directories.

After the user says “初始化我的 Skill 治理”:

1. Run `doctor` read-only. Prefer `uv`'s Python when available, then `python3` on macOS/Linux or `py -3` on Windows. If no Python 3.9+ is available, explain the required install and wait for approval.
2. Present a short status card: public root, active managed hosts, unverified candidates, errors/warnings, and the one next decision. Do not dump hashes or raw JSON unless asked.
3. Treat every discovered host as unverified. Check its profile date and official documentation, then show the exact `governance.json` addition and the expected sync result.
4. Only after confirmation may the agent create `~/.agents/skills`, write local state, create links, update managed copies, or move a cleanup target to Trash.

For a new machine, state lives under `~/.agents/` (Windows: `%USERPROFILE%\.agents\`): `skills/` is the public source, `governance.json` declares hosts and exceptions, and `skills.lock.json` records generated Skill hashes. Existing `skills-registry.json` is legacy-compatible input; never overwrite it during discovery.

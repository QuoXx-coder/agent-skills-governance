# Host Profiles

Profiles are **discovery evidence**, not permission to register or write a host. `discover` uses a matching profile only to show candidate paths, official documentation, and its verification date.

Keep user-confirmed profile updates outside this Skill package at `~/.agents/profiles/` (Windows: `%USERPROFILE%\.agents\profiles\`). `discover` and `doctor` load that directory automatically; `--profiles-dir` adds another review directory.

Every profile must contain `profile_version: 1`, `id`, `official_docs`, `verified_at`, and one or more platform entries. A platform entry declares application aliases, possible Skill roots, activation-marker candidates, and supported entry modes. It must never contain another person's absolute home path.

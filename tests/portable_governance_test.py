#!/usr/bin/env python3
"""Integration checks for the dependency-free portable governance entrypoint."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMAND = [sys.executable, str(ROOT / "scripts" / "governance.py")]


def skill_hash(source: Path) -> str:
    rows = []
    for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
        if path.is_file():
            relative = path.relative_to(source).as_posix()
            rows.append(f"{relative}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n")
    return hashlib.sha256("".join(rows).encode()).hexdigest()


class PortableGovernanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-skills-portable-test-")
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.source = self.root / "shared" / "sample-skill"
        self.source.mkdir(parents=True)
        (self.source / "SKILL.md").write_text(
            "---\nname: sample-skill\ndescription: Portable sample\n---\n",
            encoding="utf-8",
        )
        self.registry = self.root / "skills-registry.json"
        self.registry.write_text(
            json.dumps(
                {
                    "hosts": {
                        "sample-host": {
                            "platforms": {
                                "windows": {
                                    "skill_root": "AppData/Roaming/SampleHost/skills",
                                    "entry_mode": "managed_copy",
                                    "installation_markers": ["AppData/Roaming/SampleHost/settings.json"],
                                }
                            }
                        }
                    },
                    "skills": [
                        {
                            "name": "sample-skill",
                            "source_path": str(self.source),
                            "scope": "global",
                            "content_sha256": skill_hash(self.source),
                            "targets": ["sample-host"],
                            "host_exceptions": {},
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        marker = self.home / "AppData/Roaming/SampleHost/settings.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, *arguments):
        return subprocess.run(
            [*COMMAND, *arguments, "--platform", "windows", "--home", str(self.home), "--registry", str(self.registry)],
            text=True,
            capture_output=True,
            check=True,
        )

    def test_sync_creates_auditable_managed_copy_on_windows(self):
        self.run_command("sync", "--apply")

        entry = self.home / "AppData/Roaming/SampleHost/skills/sample-skill"
        manifest = entry / ".agent-skill-source.json"
        self.assertTrue(entry.is_dir())
        self.assertTrue(manifest.is_file())

        report = json.loads(self.run_command("audit", "--format", "json").stdout)
        self.assertEqual(report["summary"]["errors"], 0)

    def test_discover_reports_windows_executable_as_unverified_candidate(self):
        application_root = self.root / "Programs"
        application_root.mkdir()
        (application_root / "DoubaoWork.exe").write_bytes(b"")
        workspace = self.home / "AppData/Roaming/DoubaoWork/skills"
        workspace.mkdir(parents=True)

        result = self.run_command("discover", "--format", "json", "--applications-root", str(application_root))
        report = json.loads(result.stdout)
        candidate = next(item for item in report["candidates"] if item["name"] == "doubaowork")
        self.assertEqual(candidate["status"], "unverified")
        self.assertIn(str(workspace), candidate["possible_skill_roots"])

    def test_hash_outputs_the_registry_value_for_a_skill_source(self):
        result = subprocess.run(
            [*COMMAND, "hash", "--source", str(self.source)],
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), skill_hash(self.source))

    def test_portable_registry_template_is_valid_json(self):
        template = ROOT / "templates" / "portable-registry.json"
        data = json.loads(template.read_text(encoding="utf-8"))
        self.assertIsInstance(data["hosts"], dict)
        self.assertIsInstance(data["skills"], list)
        self.assertIn("example-agent", data["hosts"])
        self.assertEqual(data["hosts"]["example-agent"]["platforms"]["darwin"]["entry_mode"], "symlink")

    def test_audit_accepts_block_description_frontmatter(self):
        (self.source / "SKILL.md").write_text(
            "---\nname: sample-skill\ndescription: >-\n  Portable sample\n  with a second line\n---\n",
            encoding="utf-8",
        )
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        registry["hosts"] = {}
        registry["skills"][0]["targets"] = []
        registry["skills"][0]["content_sha256"] = skill_hash(self.source)
        self.registry.write_text(json.dumps(registry), encoding="utf-8")

        report = json.loads(self.run_command("audit", "--format", "json").stdout)
        self.assertEqual(report["summary"]["errors"], 0)

    def test_audit_reports_residual_broken_link_and_duplicate_real_skill(self):
        canonical_root = self.home / ".agents/skills"
        canonical_source = canonical_root / "sample-skill"
        canonical_source.parent.mkdir(parents=True)
        shutil.copytree(self.source, canonical_source)
        (canonical_source / ".DS_Store").write_bytes(b"")
        duplicate_root = self.home / "AppData/Roaming/SampleHost/skills"
        duplicate_root.mkdir(parents=True)
        shutil.copytree(self.source, duplicate_root / "sample-skill")
        # broken-symlink detection is POSIX-only: on Windows, Python's lstat
        # cannot resolve a file symlink whose target is missing, so the
        # broken-symlink issue is not reported. Guard the creation as well,
        # since creating symlinks on Windows requires admin/dev-mode.
        try:
            (duplicate_root / "broken").symlink_to(self.root / "missing")
        except (OSError, NotImplementedError):
            pass

        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        registry["skills"][0]["source_path"] = str(canonical_source)
        registry["skills"][0]["content_sha256"] = skill_hash(canonical_source)
        self.registry.write_text(json.dumps(registry), encoding="utf-8")

        report = json.loads(self.run_command("audit", "--format", "json").stdout)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("source-residual-artifact", codes)
        if os.name != "nt":
            self.assertIn("broken-symlink", codes)
        self.assertIn("duplicate-real-skill", codes)

    def test_audit_reports_missing_codex_binary_when_requested(self):
        report = json.loads(
            self.run_command(
                "audit",
                "--format",
                "json",
                "--check-codex-config",
                "--codex-bin",
                str(self.root / "missing-codex"),
            ).stdout
        )
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("codex-cli-missing", codes)

    def test_inactive_host_is_reported_without_a_missing_entry_error(self):
        marker = self.home / "AppData/Roaming/SampleHost/settings.json"
        marker.unlink()

        report = json.loads(self.run_command("audit", "--format", "json").stdout)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("host-inactive", codes)
        self.assertNotIn("managed-copy-invalid", codes)

    def test_host_exception_skips_an_unmanaged_host_directory(self):
        entry = self.home / "AppData/Roaming/SampleHost/skills/sample-skill"
        entry.mkdir(parents=True)
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        registry["skills"][0]["host_exceptions"] = {"sample-host": "host marketplace"}
        self.registry.write_text(json.dumps(registry), encoding="utf-8")

        report = json.loads(self.run_command("audit", "--format", "json").stdout)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("host-exception", codes)
        self.assertNotIn("managed-copy-invalid", codes)

    def test_host_plugin_name_conflict_is_an_error_without_an_exception(self):
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        registry["host_plugins"] = {"sample-host": [{"id": "sample-skill@host-marketplace"}]}
        self.registry.write_text(json.dumps(registry), encoding="utf-8")

        report = json.loads(self.run_command("audit", "--format", "json").stdout)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("host-plugin-name-conflict", codes)

    @unittest.skipIf(os.name == "nt", "symlink entry_mode requires macOS (darwin); Windows lacks symlink permissions by default")
    def test_sync_creates_a_darwin_symlink_for_an_active_host(self):
        home = self.root / "darwin-home"
        marker = home / ".example/settings.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")
        registry = self.root / "darwin-registry.json"
        registry.write_text(
            json.dumps(
                {
                    "hosts": {
                        "example": {
                            "platforms": {
                                "darwin": {
                                    "skill_root": ".example/skills",
                                    "entry_mode": "symlink",
                                    "installation_markers": [".example/settings.json"],
                                }
                            }
                        }
                    },
                    "skills": [{"name": "sample-skill", "source_path": str(self.source), "scope": "global", "content_sha256": skill_hash(self.source), "targets": ["example"], "host_exceptions": {}}],
                }
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [*COMMAND, "sync", "--apply", "--platform", "darwin", "--home", str(home), "--registry", str(registry)],
            text=True,
            capture_output=True,
            check=True,
        )
        entry = home / ".example/skills/sample-skill"
        self.assertTrue(entry.is_symlink())
        self.assertEqual(entry.resolve(), self.source.resolve())

    def test_sync_rejects_a_skill_name_that_escapes_the_host_root(self):
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        registry["skills"][0]["name"] = "../outside"
        self.registry.write_text(json.dumps(registry), encoding="utf-8")

        result = subprocess.run(
            [*COMMAND, "sync", "--apply", "--platform", "windows", "--home", str(self.home), "--registry", str(self.registry)],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid skill name", result.stderr)
        self.assertFalse((self.home / "AppData/Roaming/SampleHost/outside").exists())

    def test_sync_rejects_hash_drift_before_creating_an_entry(self):
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        registry["skills"][0]["content_sha256"] = "0" * 64
        self.registry.write_text(json.dumps(registry), encoding="utf-8")

        result = subprocess.run(
            [*COMMAND, "sync", "--apply", "--platform", "windows", "--home", str(self.home), "--registry", str(self.registry)],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("content hash drift", result.stderr)
        self.assertFalse((self.home / "AppData/Roaming/SampleHost/skills/sample-skill").exists())

    def test_doctor_reports_a_machine_readable_v2_direct_reader(self):
        canonical_root = self.home / ".agents/skills"
        canonical_source = canonical_root / "sample-skill"
        canonical_source.parent.mkdir(parents=True)
        shutil.copytree(self.source, canonical_source)
        governance = self.root / "governance.json"
        lock = self.root / "skills.lock.json"
        governance.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "canonical_root": str(canonical_root),
                    "hosts": {
                        "direct-host": {
                            "platforms": {
                                "windows": {
                                    "entry_mode": "direct",
                                    "direct_source_root": str(canonical_root),
                                    "activation_markers": {"mode": "any", "paths": ["AppData/Roaming/DirectHost/settings.json"]},
                                }
                            }
                        }
                    },
                    "host_plugins": {},
                }
            ),
            encoding="utf-8",
        )
        lock.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "skills": [{"name": "sample-skill", "source_path": str(canonical_source), "scope": "global", "content_sha256": skill_hash(canonical_source)}],
                }
            ),
            encoding="utf-8",
        )
        marker = self.home / "AppData/Roaming/DirectHost/settings.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")

        result = subprocess.run(
            [*COMMAND, "doctor", "--format", "json", "--platform", "windows", "--home", str(self.home), "--governance", str(governance), "--lock", str(lock)],
            text=True,
            capture_output=True,
            check=True,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["state"]["format"], "split-v2")
        self.assertEqual(report["next_step"], "review_warnings")

    def test_discover_uses_a_profile_as_unverified_evidence_only(self):
        profiles = self.home / ".agents/profiles"
        profiles.mkdir(parents=True)
        (profiles / "sample-host.json").write_text(
            json.dumps(
                {
                    "profile_version": 1,
                    "id": "profile-host",
                    "official_docs": "https://example.invalid/skills",
                    "verified_at": "2026-08-31",
                    "platforms": {
                        "windows": {
                            "application_names": ["ProfileAgent"],
                            "candidate_skill_roots": ["AppData/Roaming/ProfileAgent/skills"],
                            "activation_markers": ["AppData/Roaming/ProfileAgent/settings.json"],
                            "entry_modes": ["managed_copy"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        applications = self.root / "Programs"
        applications.mkdir()
        (applications / "ProfileAgent.exe").write_bytes(b"")

        report = json.loads(
            self.run_command(
                "discover",
                "--format",
                "json",
                "--applications-root",
                str(applications),
            ).stdout
        )
        candidate = next(item for item in report["candidates"] if item["name"] == "profile-host")
        self.assertEqual(candidate["status"], "unverified")
        self.assertEqual(candidate["profile"], "profile-host")
        self.assertIn(str(self.home / "AppData/Roaming/ProfileAgent/skills"), candidate["possible_skill_roots"])

    def test_v2_rejects_a_free_text_host_exception(self):
        canonical_root = self.home / ".agents/skills"
        canonical_source = canonical_root / "sample-skill"
        canonical_source.parent.mkdir(parents=True)
        shutil.copytree(self.source, canonical_source)
        governance = self.root / "governance.json"
        lock = self.root / "skills.lock.json"
        governance.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "canonical_root": str(canonical_root),
                    "hosts": {
                        "direct-host": {
                            "platforms": {
                                "windows": {
                                    "entry_mode": "direct",
                                    "direct_source_root": str(canonical_root),
                                    "activation_markers": {"mode": "any", "paths": ["AppData/Roaming/DirectHost/settings.json"]},
                                }
                            }
                        }
                    },
                    "host_plugins": {"direct-host": [{"id": "sample-skill@builtin"}]},
                }
            ),
            encoding="utf-8",
        )
        lock.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "skills": [{"name": "sample-skill", "source_path": str(canonical_source), "scope": "global", "content_sha256": skill_hash(canonical_source), "host_exceptions": {"direct-host": "marketplace"}}],
                }
            ),
            encoding="utf-8",
        )
        marker = self.home / "AppData/Roaming/DirectHost/settings.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")

        result = subprocess.run(
            [*COMMAND, "audit", "--format", "json", "--platform", "windows", "--home", str(self.home), "--governance", str(governance), "--lock", str(lock)],
            text=True,
            capture_output=True,
            check=True,
        )
        codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
        self.assertIn("host-exception-invalid", codes)


if __name__ == "__main__":
    unittest.main()

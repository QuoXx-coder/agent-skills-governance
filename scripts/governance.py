#!/usr/bin/env python3
"""Dependency-free, cross-platform Skill governance for JSON registries."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import platform as runtime_platform
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


MANAGED_COPY_MARKER = ".agent-skill-source.json"
IGNORED_FILES = {".DS_Store", MANAGED_COPY_MARKER}
IGNORED_DIRECTORIES = {".git", "__pycache__"}
AGENT_APP = re.compile(r"codex|claude|cursor|qoder|workbuddy|doubao|trae|codebuddy", re.I)
AUXILIARY_APP = re.compile(r"url handler", re.I)
SAFE_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
BUILTIN_PROFILES_DIR = Path(__file__).resolve().parents[1] / "profiles"


def current_platform():
    name = runtime_platform.system().lower()
    return {"darwin": "darwin", "windows": "windows"}.get(name, "linux")


def expand_path(value, home):
    value = str(value).replace("${HOME}", str(home)).replace("%USERPROFILE%", str(home))
    path = Path(value).expanduser()
    return path if path.is_absolute() else home / path


def load_registry(path):
    if path.suffix.lower() != ".json":
        raise ValueError("governance accepts JSON registries only")
    with path.open(encoding="utf-8") as handle:
        registry = json.load(handle)
    if not isinstance(registry, dict) or not isinstance(registry.get("skills"), list):
        raise ValueError("registry root must be an object with a skills array")
    return registry


def load_json_document(path, label):
    with Path(path).open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError("{} must be a JSON object".format(label))
    return document


def load_state(arguments):
    governance_path = getattr(arguments, "governance", None)
    lock_path = getattr(arguments, "lock", None)
    if governance_path or lock_path:
        if not governance_path or not lock_path:
            raise ValueError("--governance and --lock must be used together")
        governance = load_json_document(governance_path, "governance")
        lock = load_json_document(lock_path, "skills lock")
        if governance.get("schema_version") != 2:
            raise ValueError("governance schema_version must be 2")
        if lock.get("schema_version") != 1 or not isinstance(lock.get("skills"), list):
            raise ValueError("skills lock schema_version must be 1 with a skills array")
        registry = {
            "schema_version": 2,
            "hosts": governance.get("hosts", {}),
            "host_plugins": governance.get("host_plugins", {}),
            "skills": lock["skills"],
        }
        return registry, {
            "format": "split-v2",
            "governance": str(governance_path),
            "lock": str(lock_path),
            "canonical_root": governance.get("canonical_root"),
        }
    registry_path = Path(arguments.registry).expanduser()
    return load_registry(registry_path), {"format": "legacy-v1", "registry": str(registry_path), "canonical_root": None}


def content_hash(root):
    root = root.resolve()
    rows = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if not path.is_file() or path.name in IGNORED_FILES:
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue
        rows.append("{}\0{}\n".format(relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256("".join(rows).encode("utf-8")).hexdigest()


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not match:
        raise ValueError("missing YAML frontmatter")
    metadata = match.group(1)
    name = re.search(r"^name:\s*(.+?)\s*$", metadata, re.M)
    description = re.search(r"^description:\s*(.+?)\s*$", metadata, re.M)
    if not name or not description:
        raise ValueError("frontmatter requires name and description")
    description_value = description.group(1).strip()
    if description_value in {">", ">-", "|", "|-"}:
        following = metadata[description.end():]
        block = []
        for line in following.splitlines():
            if line and not line[0].isspace():
                break
            if line.strip():
                block.append(line.strip())
        description_value = " ".join(block)
    return {"name": name.group(1).strip(" '\""), "description": description_value}


def add_issue(issues, severity, code, message, path=None, suggestion=None):
    item = {"severity": severity, "code": code, "message": message}
    if path is not None:
        item["path"] = str(path)
    if suggestion is not None:
        item["suggestion"] = suggestion
    issues.append(item)


def host_configurations(registry, home, selected_platform, issues, registry_path):
    raw_hosts = registry.get("hosts")
    if not isinstance(raw_hosts, dict):
        add_issue(issues, "error", "hosts-missing", "注册表缺少宿主配置。", registry_path)
        return {}

    result = {}
    for name, raw in raw_hosts.items():
        raw = raw if isinstance(raw, dict) else {}
        platform_configs = raw.get("platforms")
        config = platform_configs.get(selected_platform) if isinstance(platform_configs, dict) else raw
        if not isinstance(config, dict):
            result[str(name)] = {"supported": False}
            continue
        mode = config.get("entry_mode")
        activation = config.get("activation_markers")
        markers = config.get("installation_markers")
        marker_mode = "any"
        if isinstance(activation, dict):
            marker_mode = activation.get("mode")
            markers = activation.get("paths")
        direct_root = config.get("direct_source_root")
        root = config.get("skill_root")
        is_v2 = registry.get("schema_version") == 2
        if mode not in {"direct", "symlink", "managed_copy"} or not isinstance(markers, list) or not markers or marker_mode not in {"any", "all"}:
            add_issue(issues, "error", "host-config-invalid", "{} 的 {} 平台宿主配置不完整。".format(name, selected_platform), registry_path)
            continue
        if mode == "direct":
            if is_v2 and not direct_root:
                add_issue(issues, "error", "host-config-invalid", "{} 的 direct 宿主必须声明 direct_source_root。".format(name), registry_path)
                continue
            root = direct_root or root
        if not root:
            add_issue(issues, "error", "host-config-invalid", "{} 的 {} 平台缺少 Skill 根目录。".format(name, selected_platform), registry_path)
            continue
        marker_paths = [expand_path(marker, home) for marker in markers]
        result[str(name)] = {
            "supported": True,
            "root": expand_path(root, home),
            "entry_mode": mode,
            "markers": marker_paths,
            "marker_mode": marker_mode,
            "direct_source_root": expand_path(direct_root, home) if direct_root else None,
            "active": any(marker.exists() for marker in marker_paths) if marker_mode == "any" else all(marker.exists() for marker in marker_paths),
        }
    return result


def host_plugin_names(registry, hosts, issues, registry_path):
    raw = registry.get("host_plugins", {})
    if not isinstance(raw, dict):
        add_issue(issues, "error", "host-plugins-invalid", "host_plugins 必须是映射。", registry_path)
        return {}
    names = {}
    for host, entries in raw.items():
        if host not in hosts:
            add_issue(issues, "error", "host-plugin-host-unregistered", "{} 的宿主插件没有对应宿主配置。".format(host), registry_path)
            continue
        if not isinstance(entries, list):
            add_issue(issues, "error", "host-plugins-invalid", "{} 的 host_plugins 必须是数组。".format(host), registry_path)
            continue
        values = []
        for entry in entries:
            plugin_id = entry.get("id", "").strip() if isinstance(entry, dict) else ""
            if not plugin_id:
                add_issue(issues, "error", "host-plugin-invalid", "{} 存在缺少 id 的插件记录。".format(host), registry_path)
            else:
                values.append(plugin_id.split("@", 1)[0])
        names[str(host)] = values
    return names


def validated_host_exception(raw, name, host_name, plugins, is_v2, issues=None, path=None):
    if raw is None:
        return None
    if not is_v2:
        value = str(raw).strip()
        return value or None
    valid = (
        isinstance(raw, dict)
        and raw.get("kind") in {"marketplace", "builtin"}
        and isinstance(raw.get("source"), str)
        and bool(raw["source"].strip())
        and isinstance(raw.get("reason"), str)
        and bool(raw["reason"].strip())
        and name in plugins.get(host_name, [])
    )
    if not valid:
        if issues is not None:
            add_issue(issues, "error", "host-exception-invalid", "v2 host_exception 必须含 kind/source/reason，并匹配已登记的同名宿主插件。", path)
        return None
    return raw


def managed_copy_state(entry, source, expected_hash):
    marker = entry / MANAGED_COPY_MARKER
    if entry.is_symlink() or not entry.is_dir() or not marker.is_file():
        return "invalid"
    try:
        manifest = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid"
    if manifest.get("source") != str(source.resolve()):
        return "stale"
    return "current" if manifest.get("content_sha256") == expected_hash and content_hash(entry) == expected_hash else "stale"


def write_managed_copy(source, entry, expected_hash):
    staging = Path(tempfile.mkdtemp(prefix=".{}-staging-".format(entry.name), dir=entry.parent))
    backup = entry.parent / ".{}-backup-{}".format(entry.name, uuid.uuid4().hex)
    try:
        shutil.rmtree(staging)
        shutil.copytree(source, staging)
        (staging / MANAGED_COPY_MARKER).write_text(
            json.dumps({"source": str(source.resolve()), "content_sha256": expected_hash}, indent=2) + "\n",
            encoding="utf-8",
        )
        if entry.exists() or entry.is_symlink():
            entry.replace(backup)
        staging.replace(entry)
        if backup.exists() or backup.is_symlink():
            shutil.rmtree(backup)
    except Exception:
        if not entry.exists() and (backup.exists() or backup.is_symlink()):
            backup.replace(entry)
        raise
    finally:
        if staging.exists() or staging.is_symlink():
            shutil.rmtree(staging)


def report_source_residuals(source, issues):
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if path.name == ".DS_Store" or path.suffix == ".pyc" or "__pycache__" in relative.parts:
            add_issue(issues, "warning", "source-residual-artifact", "注册真源中存在可清理残留。", path)


def report_broken_symlinks(hosts, issues):
    for host_name, host in hosts.items():
        if not host.get("active") or not host.get("supported") or not host["root"].is_dir():
            continue
        for path in host["root"].rglob("*"):
            if path.is_symlink() and not path.exists():
                add_issue(issues, "error", "broken-symlink", "{} Skill 根目录存在悬空软链接。".format(host_name), path)


def report_duplicate_real_skills(skills, hosts, canonical_root, issues):
    exception_paths = set()
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        exceptions = skill.get("host_exceptions", {})
        if not isinstance(exceptions, dict):
            continue
        for host_name, reason in exceptions.items():
            host = hosts.get(str(host_name))
            if host and host.get("supported") and str(reason).strip():
                exception_paths.add((host["root"] / str(skill.get("name", ""))).resolve())

    locations = {}
    roots = [canonical_root] + [host["root"] for host in hosts.values() if host.get("active") and host.get("supported")]
    for root in sorted(set(roots), key=str):
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if path.is_symlink() or not path.is_dir() or path.resolve() in exception_paths:
                continue
            marker = path / "SKILL.md"
            if not marker.is_file():
                continue
            try:
                name = frontmatter(marker)["name"]
            except (OSError, ValueError):
                continue
            locations.setdefault(name, []).append(path)
    for name, paths in locations.items():
        if len(paths) > 1:
            add_issue(issues, "warning", "duplicate-real-skill", "同名 Skill 存在多个真实目录：{}".format(", ".join(str(path) for path in paths)), paths[0])


def report_codex_config(arguments, issues):
    if not arguments.check_codex_config:
        return
    try:
        result = subprocess.run(
            [arguments.codex_bin, "app-server", "--strict-config", "--stdio"],
            input="",
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError:
        add_issue(issues, "warning", "codex-cli-missing", "PATH 中找不到 codex，已跳过严格配置校验。")
        return
    except subprocess.TimeoutExpired:
        add_issue(issues, "warning", "codex-config-drift", "Codex 严格配置校验超时。", arguments.home / ".codex/config.toml")
        return
    if result.returncode:
        detail = " ".join((result.stdout + " " + result.stderr).split())
        add_issue(issues, "warning", "codex-config-drift", "当前 Codex 严格配置校验失败：{}".format(detail), arguments.home / ".codex/config.toml")


def skill_targets(skill, hosts):
    targets = skill.get("targets")
    if targets is None:
        return sorted(hosts)
    return [str(target) for target in targets] if isinstance(targets, list) else []


def safe_skill_name(name):
    return bool(SAFE_SKILL_NAME.fullmatch(name))


def source_for(skill, home):
    value = skill.get("source_path") if isinstance(skill, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    return expand_path(value, home)


def direct_source_is_valid(host, source, canonical_root):
    if host.get("direct_source_root") is None:
        return True  # Legacy-v1 direct readers remain readable but are not evidence-backed.
    direct_root = host["direct_source_root"].resolve()
    return source.parent.resolve() == direct_root and direct_root == canonical_root.resolve()


def audit(arguments):
    issues = []
    try:
        registry, state = load_state(arguments)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        registry_path = Path(getattr(arguments, "governance", None) or arguments.registry).expanduser()
        add_issue(issues, "error", "registry-invalid", "注册表无法解析：{}".format(error), registry_path)
        registry = {"skills": []}
        state = {"format": "unavailable", "registry": str(registry_path), "canonical_root": None}

    registry_path = Path(state.get("governance") or state.get("registry") or arguments.registry)

    hosts = host_configurations(registry, arguments.home, arguments.platform, issues, registry_path)
    plugins = host_plugin_names(registry, hosts, issues, registry_path)
    skills = registry.get("skills", [])
    names = [entry.get("name") for entry in skills if isinstance(entry, dict)]
    for name in sorted({item for item in names if names.count(item) > 1}):
        add_issue(issues, "error", "registry-duplicate-name", "注册表名称不唯一：{}。".format(name), registry_path)

    for skill in skills:
        if not isinstance(skill, dict):
            add_issue(issues, "error", "skill-invalid", "skills 条目必须是对象。", registry_path)
            continue
        name = str(skill.get("name", ""))
        source = source_for(skill, arguments.home)
        scope = str(skill.get("scope", ""))
        targets = skill_targets(skill, hosts)
        exceptions = skill.get("host_exceptions", {}) if isinstance(skill.get("host_exceptions", {}), dict) else {}
        if not safe_skill_name(name):
            add_issue(issues, "error", "skill-name-invalid", "Skill 名称不是安全目录名。", registry_path)
            continue
        if source is None:
            add_issue(issues, "error", "source-path-missing", "Skill 缺少 source_path。", registry_path)
            continue
        marker = source / "SKILL.md"
        if not source.is_dir():
            add_issue(issues, "error", "source-missing", "Skill 真源不存在。", source)
            continue
        if not marker.is_file():
            add_issue(issues, "error", "skill-marker-missing", "真源缺少 SKILL.md。", source)
            continue
        try:
            metadata = frontmatter(marker)
            if metadata["name"] != name:
                add_issue(issues, "error", "frontmatter-name-mismatch", "frontmatter 名称与注册表不一致。", marker)
            if not metadata["description"] or metadata["description"] == ">-":
                add_issue(issues, "error", "frontmatter-description-invalid", "description 缺失或无效。", marker)
            if source.name != name:
                add_issue(issues, "error", "directory-name-mismatch", "真源目录名与 Skill 名称不一致。", source)
        except (OSError, ValueError) as error:
            add_issue(issues, "error", "frontmatter-invalid", "SKILL.md frontmatter 无法解析：{}".format(error), marker)

        expected_hash = str(skill.get("content_sha256", ""))
        actual_hash = content_hash(source)
        if expected_hash != actual_hash:
            add_issue(issues, "error", "content-hash-drift", "内容哈希与注册表不一致；expected={} actual={}。".format(expected_hash, actual_hash), source)

        report_source_residuals(source, issues)

        for host_name in targets:
            host = hosts.get(host_name)
            if host is None:
                add_issue(issues, "error", "host-target-unregistered", "{} 是登记目标，但不是已接入宿主。".format(host_name), registry_path)
                continue
            if not host.get("supported"):
                add_issue(issues, "info", "host-platform-unsupported", "{} 未提供 {} 平台配置，已跳过。".format(host_name, arguments.platform), registry_path)
                continue
            if not host["active"]:
                add_issue(issues, "info", "host-inactive", "{} 未检测到安装标记，已跳过入口治理。".format(host_name), host["root"])
                continue
            exception = validated_host_exception(exceptions.get(host_name), name, host_name, plugins, registry.get("schema_version") == 2, issues, source)
            if scope == "global" and name in plugins.get(host_name, []) and not exception:
                add_issue(issues, "error", "host-plugin-name-conflict", "{} 的宿主插件与公共 Skill 同名，但未登记例外。".format(host_name), source)
            if exception:
                reason = exception["reason"] if isinstance(exception, dict) else exception
                add_issue(issues, "info", "host-exception", "{} 使用已登记的宿主例外：{}".format(host_name, reason), source)
                continue
            entry = host["root"] / name
            if scope == "host" and entry.resolve() == source.resolve():
                if not entry.is_dir() or entry.is_symlink():
                    add_issue(issues, "error", "host-source-invalid", "宿主专属真源不是预期真实目录。", entry)
                continue
            if scope == "global" and host["entry_mode"] == "direct":
                canonical_root = Path(state.get("canonical_root") or arguments.canonical_root or arguments.home / ".agents/skills")
                if host.get("direct_source_root") and not direct_source_is_valid(host, source, canonical_root):
                    add_issue(issues, "error", "direct-source-root-invalid", "direct_source_root 必须等于公共真源，且 Skill 必须位于其直接子目录。", source)
                elif not host.get("direct_source_root"):
                    if entry.is_symlink():
                        add_issue(issues, "warning", "redundant-direct-reader-link", "直接读取宿主存在冗余软链接。", entry)
                    elif entry.exists():
                        add_issue(issues, "error", "duplicate-real-directory", "直接读取宿主存在同名真实目录。", entry)
                continue
            if host["entry_mode"] == "managed_copy":
                copy_state = managed_copy_state(entry, source, expected_hash)
                if copy_state == "invalid":
                    add_issue(issues, "error", "managed-copy-invalid", "受管副本缺少有效来源清单。", entry)
                elif copy_state == "stale":
                    add_issue(issues, "error", "managed-copy-stale", "受管副本与登记真源不一致。", entry)
                continue
            if not entry.is_symlink():
                add_issue(issues, "error", "host-entry-invalid", "宿主入口缺失或不是预期软链接。", entry)
            elif entry.resolve() != source.resolve():
                add_issue(issues, "error", "host-entry-wrong-target", "宿主入口没有指向登记真源。", entry)

    report_broken_symlinks(hosts, issues)
    canonical_root = Path(state.get("canonical_root") or arguments.canonical_root or arguments.home / ".agents/skills")
    report_duplicate_real_skills(skills, hosts, canonical_root, issues)

    temp_root = Path(arguments.temp_root)
    if temp_root.is_dir():
        for path in sorted(temp_root.glob("agent-skills-*")):
            add_issue(issues, "warning", "temporary-artifact", "发现 Agent Skill 临时目录。", path)

    report_codex_config(arguments, issues)

    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda item: (order[item["severity"]], item["code"], item.get("path", "")))
    summary = {
        "registry": str(registry_path),
        "platform": arguments.platform,
        "managed_skills": len(skills),
        "active_hosts": sum(1 for host in hosts.values() if host.get("active")),
        "errors": sum(1 for issue in issues if issue["severity"] == "error"),
        "warnings": sum(1 for issue in issues if issue["severity"] == "warning"),
        "info": sum(1 for issue in issues if issue["severity"] == "info"),
    }
    report = {"summary": summary, "issues": issues, "state": state}
    if arguments.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("# Portable Agent Skills audit")
        print("errors={} warnings={} info={}".format(summary["errors"], summary["warnings"], summary["info"]))
        for issue in issues:
            print("[{}] {}: {}".format(issue["severity"].upper(), issue["code"], issue["message"]))
    return 1 if arguments.strict and (summary["errors"] or summary["warnings"]) else 0


def sync_preflight(registry, hosts, home, canonical_root, plugins):
    issues = []
    for skill in registry.get("skills", []):
        if not isinstance(skill, dict) or skill.get("scope") != "global":
            continue
        name = str(skill.get("name", ""))
        if not safe_skill_name(name):
            issues.append("invalid skill name ({})".format(name))
            continue
        source = source_for(skill, home)
        if source is None:
            issues.append("{}: source_path is missing".format(name))
            continue
        marker = source / "SKILL.md"
        if not source.is_dir() or not marker.is_file():
            issues.append("{}: source must be a directory containing SKILL.md ({})".format(name, source))
            continue
        try:
            metadata = frontmatter(marker)
        except (OSError, ValueError) as error:
            issues.append("{}: invalid frontmatter ({})".format(name, error))
            continue
        if metadata["name"] != name or source.name != name or not metadata["description"]:
            issues.append("{}: source name, directory name, and frontmatter must match".format(name))
            continue
        expected_hash = str(skill.get("content_sha256", ""))
        if expected_hash != content_hash(source):
            issues.append("{}: content hash drift".format(name))
            continue
        for host_name in skill_targets(skill, hosts):
            host = hosts.get(host_name)
            if host is None:
                issues.append("{}: target host is not registered ({})".format(name, host_name))
                continue
            if host.get("entry_mode") == "direct" and host.get("direct_source_root") and not direct_source_is_valid(host, source, canonical_root):
                issues.append("{}: direct_source_root is not the canonical source".format(name))
            raw_exception = skill.get("host_exceptions", {}).get(host_name) if isinstance(skill.get("host_exceptions", {}), dict) else None
            if raw_exception is not None and not validated_host_exception(raw_exception, name, host_name, plugins, registry.get("schema_version") == 2):
                issues.append("{}: invalid host exception for {}".format(name, host_name))
    return issues


def sync(arguments):
    try:
        registry, state = load_state(arguments)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("ERROR: registry cannot be loaded: {}".format(error), file=sys.stderr)
        return 1
    issues = []
    registry_path = Path(state.get("governance") or state.get("registry") or arguments.registry)
    hosts = host_configurations(registry, arguments.home, arguments.platform, issues, registry_path)
    plugins = host_plugin_names(registry, hosts, issues, registry_path)
    canonical_root = Path(state.get("canonical_root") or arguments.home / ".agents/skills")
    issues.extend(sync_preflight(registry, hosts, arguments.home, canonical_root, plugins))
    if issues:
        print("# Portable active-host synchronization blocked by preflight", file=sys.stderr)
        for issue in issues:
            print("ERROR: {}".format(issue), file=sys.stderr)
        return 1
    actions = []
    for skill in registry["skills"]:
        if not isinstance(skill, dict) or skill.get("scope") != "global":
            continue
        name = str(skill.get("name", ""))
        source = source_for(skill, arguments.home)
        expected_hash = str(skill.get("content_sha256", ""))
        for host_name in skill_targets(skill, hosts):
            host = hosts.get(host_name)
            if not host or not host.get("supported") or not host.get("active") or host["entry_mode"] == "direct":
                continue
            exceptions = skill.get("host_exceptions", {})
            if isinstance(exceptions, dict) and str(exceptions.get(str(host_name), "")).strip():
                continue
            entry = host["root"] / name
            if host["entry_mode"] == "managed_copy":
                state = managed_copy_state(entry, source, expected_hash) if entry.exists() or entry.is_symlink() else "missing"
                if state == "current":
                    actions.append("unchanged {}".format(entry))
                elif state == "invalid":
                    issues.append("{}: unmanaged real path will not be replaced ({})".format(name, entry))
                else:
                    actions.append("{} {} <= {}".format("create" if state == "missing" else "update", entry, source))
                    if arguments.apply:
                        entry.parent.mkdir(parents=True, exist_ok=True)
                        write_managed_copy(source, entry, expected_hash)
                continue
            if entry.is_symlink() and entry.resolve() == source.resolve():
                actions.append("unchanged {}".format(entry))
            elif entry.exists() or entry.is_symlink():
                issues.append("{}: existing path will not be replaced ({})".format(name, entry))
            else:
                actions.append("create {} -> {}".format(entry, source))
                if arguments.apply:
                    entry.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.symlink(source, entry, target_is_directory=True)
                    except OSError as error:
                        issues.append("{}: unable to create symlink: {}".format(name, error))
    print("# Portable active-host synchronization{}".format("" if arguments.apply else " (dry run)"))
    for action in actions:
        print(action)
    for issue in issues:
        print("ERROR: {}".format(issue), file=sys.stderr)
    if not arguments.apply:
        print("No filesystem changes were made.")
    return 1 if issues else 0


def candidate_paths(name, home, selected_platform):
    if selected_platform == "windows":
        roots = [home / "AppData/Roaming" / name, home / "AppData/Local" / name]
    elif selected_platform == "darwin":
        roots = [home / name, home / "Library/Application Support" / name]
    else:
        roots = [home / ".local/share" / name, home / name]
    possible = [root / "skills" for root in roots if (root / "skills").is_dir()]
    observed = [path for root in roots for path in (root, root / "skills") if path.exists()]
    return observed, possible


def normalized_name(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def load_profiles(arguments):
    directories = [BUILTIN_PROFILES_DIR, arguments.home / ".agents/profiles"] + [Path(path) for path in arguments.profiles_dir]
    profiles = []
    seen = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                profile = load_json_document(path, "host profile")
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            profile_id = profile.get("id")
            if profile.get("profile_version") != 1 or not isinstance(profile_id, str) or not profile_id or profile_id in seen:
                continue
            if not isinstance(profile.get("platforms"), dict) or not isinstance(profile.get("official_docs"), str) or not profile.get("official_docs"):
                continue
            seen.add(profile_id)
            profiles.append(profile)
    return profiles


def profile_candidate(profile, application, home, selected_platform):
    platform_config = profile["platforms"].get(selected_platform)
    if not isinstance(platform_config, dict):
        return None
    aliases = platform_config.get("application_names")
    if not isinstance(aliases, list) or normalized_name(application.stem) not in {normalized_name(alias) for alias in aliases}:
        return None
    root_values = platform_config.get("candidate_skill_roots", [])
    roots = [expand_path(value, home) for value in root_values if isinstance(value, str)]
    observed = [application] + [root for root in roots if root.exists()]
    return {
        "name": profile["id"],
        "application": str(application),
        "status": "unverified",
        "profile": profile["id"],
        "official_docs": profile["official_docs"],
        "verified_at": profile.get("verified_at"),
        "observed_paths": [str(item) for item in observed],
        "possible_skill_roots": [str(item) for item in roots],
        "next_step": "Verify the official mechanism and local path, then show a registration plan for confirmation.",
    }


def discover(arguments):
    registry, _ = load_state(arguments)
    registered = {normalized_name(name) for name in registry.get("hosts", {})}
    profiles = load_profiles(arguments)
    roots = [Path(root) for root in arguments.applications_root]
    if not roots:
        if arguments.platform == "windows":
            roots = [arguments.home / "AppData/Local/Programs", arguments.home / "AppData/Roaming"]
        elif arguments.platform == "darwin":
            roots = [Path("/Applications"), arguments.home / "Applications"]
        else:
            roots = [arguments.home / ".local/share/applications"]
    candidates = []
    for root in sorted(set(roots), key=str):
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            is_candidate_file = arguments.platform == "windows" and path.is_file() and path.suffix.lower() == ".exe"
            is_candidate_directory = path.is_dir() and (arguments.platform != "darwin" or path.suffix.lower() == ".app")
            if not (is_candidate_file or is_candidate_directory):
                continue
            app_name = path.stem if path.suffix.lower() in {".app", ".exe"} else path.name
            normalized = normalized_name(app_name)
            if normalized in registered or AUXILIARY_APP.search(app_name):
                continue
            matched_profile = next((profile_candidate(profile, path, arguments.home, arguments.platform) for profile in profiles if profile_candidate(profile, path, arguments.home, arguments.platform)), None)
            if matched_profile:
                if normalized_name(matched_profile["name"]) not in registered:
                    candidates.append(matched_profile)
                continue
            observed, possible = candidate_paths(app_name, arguments.home, arguments.platform)
            if not AGENT_APP.search(app_name) and not possible:
                continue
            candidates.append({
                "name": normalized,
                "application": str(path),
                "status": "unverified",
                "observed_paths": [str(item) for item in observed],
                "possible_skill_roots": [str(item) for item in possible],
                "next_step": "Verify the official discovery mechanism before registering this host.",
            })
    report = {"platform": arguments.platform, "registered_hosts": sorted(registry.get("hosts", {}).keys()), "candidates": candidates, "writes": False}
    if arguments.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("# Candidate host discovery (read only)")
        for candidate in candidates:
            print("- {}: {}".format(candidate["name"], candidate["application"]))
        print("No filesystem or registry changes were made.")
    return 0


def doctor(arguments):
    audit_stream = io.StringIO()
    original_format = arguments.format
    original_strict = arguments.strict
    arguments.format = "json"
    arguments.strict = False
    with contextlib.redirect_stdout(audit_stream):
        audit(arguments)
    arguments.format = original_format
    arguments.strict = original_strict
    audit_report = json.loads(audit_stream.getvalue())

    discovery_stream = io.StringIO()
    with contextlib.redirect_stdout(discovery_stream):
        discover(arguments)
    discovery_report = json.loads(discovery_stream.getvalue())
    summary = audit_report["summary"]
    next_step = "fix_errors" if summary["errors"] else "review_warnings" if summary["warnings"] else "healthy"
    report = {
        "summary": summary,
        "state": audit_report["state"],
        "runtime": {"python": sys.version.split()[0], "executable": sys.executable},
        "candidates": discovery_report["candidates"],
        "next_step": next_step,
        "writes": False,
    }
    if arguments.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("# Agent Skills governance doctor")
        print("state={} errors={} warnings={} candidates={}".format(report["state"]["format"], summary["errors"], summary["warnings"], len(report["candidates"])))
        print("next_step={}".format(next_step))
    return 1 if arguments.strict and (summary["errors"] or summary["warnings"]) else 0


def print_hash(arguments):
    source = Path(arguments.source).expanduser()
    if not source.is_dir():
        raise ValueError("Skill source does not exist: {}".format(source))
    print(content_hash(source))
    return 0


def add_common_arguments(parser):
    parser.add_argument("--platform", choices=["darwin", "windows", "linux"], default=current_platform())
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--registry", type=Path, default=Path.home() / ".agents/skills-registry.json", help="JSON registry path")
    parser.add_argument("--governance", type=Path, help="v2 governance.json path; requires --lock")
    parser.add_argument("--lock", type=Path, help="v2 skills.lock.json path; requires --governance")


def main():
    parser = argparse.ArgumentParser(description="Portable Agent Skills governance")
    commands = parser.add_subparsers(dest="command", required=True)
    audit_parser = commands.add_parser("audit")
    add_common_arguments(audit_parser)
    audit_parser.add_argument("--format", choices=["text", "json"], default="text")
    audit_parser.add_argument("--strict", action="store_true")
    audit_parser.add_argument("--temp-root", type=Path, default=Path(tempfile.gettempdir()))
    audit_parser.add_argument("--canonical-root", type=Path, help="canonical shared Skill root")
    audit_parser.add_argument("--check-codex-config", action="store_true")
    audit_parser.add_argument("--codex-bin", default="codex")
    sync_parser = commands.add_parser("sync")
    add_common_arguments(sync_parser)
    sync_parser.add_argument("--apply", action="store_true")
    discover_parser = commands.add_parser("discover")
    add_common_arguments(discover_parser)
    discover_parser.add_argument("--format", choices=["text", "json"], default="text")
    discover_parser.add_argument("--applications-root", action="append", default=[])
    discover_parser.add_argument("--profiles-dir", action="append", default=[])
    doctor_parser = commands.add_parser("doctor")
    add_common_arguments(doctor_parser)
    doctor_parser.add_argument("--format", choices=["text", "json"], default="text")
    doctor_parser.add_argument("--strict", action="store_true")
    doctor_parser.add_argument("--temp-root", type=Path, default=Path(tempfile.gettempdir()))
    doctor_parser.add_argument("--canonical-root", type=Path, help="canonical shared Skill root")
    doctor_parser.add_argument("--check-codex-config", action="store_true")
    doctor_parser.add_argument("--codex-bin", default="codex")
    doctor_parser.add_argument("--applications-root", action="append", default=[])
    doctor_parser.add_argument("--profiles-dir", action="append", default=[])
    hash_parser = commands.add_parser("hash")
    hash_parser.add_argument("--source", required=True, help="Skill source directory")
    arguments = parser.parse_args()
    return {"audit": audit, "sync": sync, "discover": discover, "doctor": doctor, "hash": print_hash}[arguments.command](arguments)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        sys.exit(2)

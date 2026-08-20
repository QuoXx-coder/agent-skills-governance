---
name: agent-skills-governance
description: >-
  审计本机多个智能体的 Skill 真源、注册表哈希、frontmatter、断链、重复真实目录、宿主入口、配置漂移和临时文件残留；当用户提出“检查所有 Skills”“清理前先审计”“Skill 是否同步”“定期巡检智能体能力”或需要验证 Codex、Claude、Cursor、Qoder、WorkBuddy 的 Skill 治理状态时使用。
  Audit local multi-agent Skill sources, registry hashes, frontmatter, broken links, duplicate real directories, host visibility, configuration drift, and temporary artifacts; use for Skill inventory, synchronization checks, cleanup previews, or recurring governance across Codex, Claude, Cursor, Qoder, and WorkBuddy.
---

# Agent Skills Governance

## 核心原则

把公共 Skill 视为可维护资产，而不是散落副本。默认只读审计；报告问题不等于授权修复。

- 公共真源默认位于 `~/.agents/skills`。
- Codex 和 Cursor 直接读取公共真源；Claude、Qoder 使用软链接。WorkBuddy 仅在没有可用的官方 Marketplace/内置版本、且需要跨宿主一致时使用软链接；注册表明确记录的宿主例外除外。
- 项目 Skill 保留项目真源，只建立薄入口。
- 系统、插件缓存、Marketplace 和宿主内置 Skill 保持宿主专属，不擅自收编。
- 若 WorkBuddy 的官方 Marketplace 或内置能力已提供同名 Skill，则该版本是 WorkBuddy 的真源：登记 `host_exception`（注明市场/内置来源），不创建公共真源软链接，也不把它作为重复真实目录处理。
- 同名 Skill 先比较来源归属、实际能力和升级路径；每个宿主只能选定一个权威来源。没有用户确认，不得用公共版覆盖市场版、用市场版覆盖公共版，或把任一版本收编进另一方。
- 删除、覆盖、迁移、重命名、隔离或修改配置前，先展示精确目标和影响并获得确认。

## 只读巡检

从本 Skill 目录运行：

```bash
scripts/audit-skills
```

需要机器可读结果时：

```bash
scripts/audit-skills --format json
```

需要让任何 warning/error 导致非零退出时：

```bash
scripts/audit-skills --strict
```

需要额外检查当前 Codex CLI 能否严格解析配置时（默认不执行）：

```bash
scripts/audit-skills --check-codex-config
```

默认巡检只读取以下对象：

- `~/.agents/skills-registry.yaml`
- 五个用户级 Skill 根目录
- 注册表指向的 Skill 真源
- `/private/tmp/agent-skills-*` 临时目录

它不扫描用户明确排除、且不在注册表中的项目目录。

`--check-codex-config` 会额外调用当前 PATH 中的 Codex CLI，以严格模式读取配置；它不修改配置，但具体运行行为会受本机 Codex 配置影响。默认巡检不会调用 Codex。

## 检查内容

1. 验证注册表能解析，名称唯一，来源存在，内容哈希与登记值一致。
2. 验证每个 `SKILL.md` frontmatter 含合法 `name` 和 `description`，目录名与 `name` 一致。
3. 验证公共 Skill 的五宿主入口；尊重 `host_exceptions`。
4. 查找用户级 Skill 根目录中的悬空软链接和同名真实副本。
5. 查找注册真源中的 `.DS_Store`、`__pycache__`、`.pyc` 等残留。
6. 查找 `/private/tmp/agent-skills-*` 审计临时目录。
7. 使用 `--check-codex-config` 时，用当前 Codex CLI 严格解析配置，报告已经失效或未知的字段。

## 报告与修复边界

按严重性输出：

- `error`：来源缺失、哈希漂移、frontmatter 无效、入口错误或断链。
- `warning`：重复真实目录、配置漂移、审计临时目录或可疑残留。
- `info`：已登记且合理的宿主例外等说明。

报告至少包含问题代码、精确路径、原因和建议。发现问题后先汇总拟议动作；只有用户在当前交互任务中明确确认具体目标，才调用合适工具执行修复。

定时巡检永远停在报告阶段，不自动修复，也不把“清理一次”的历史授权当作未来持续授权。

## 受管 Skill 变更后的注册表同步

当用户在当前交互任务中明确授权安装、更新或修复一个已登记 Skill 时，该授权默认包含同一工作流内的注册表 hash 收尾：

1. 确认变更来源可信，并定位 `~/.agents/skills-registry.yaml` 中对应的唯一条目。
2. 按 `scripts/audit-skills` 使用的算法重新计算当前内容 hash。
3. 先说明目标 Skill、旧 hash、新 hash 和影响；若只替换该条目的 `content_sha256`，无需再次索要确认。
4. 更新后重新运行审计；`content-hash-drift` 必须为 0，才可宣布更新完成。

这项默认授权只覆盖由本轮已授权 Skill 变更直接造成的 `content_sha256` 更新。来源不明的漂移，或涉及 `source_path`、`source_kind`、`origin`、`targets`、`host_exceptions` 等字段的变化，仍须先报告并获得明确确认。

定时只读巡检不得自动接受 hash 漂移或修改注册表。它只能报告漂移并等待交互任务确认，因为定时任务无法仅凭“当前文件已变化”判断这是可信更新还是未授权修改。

## 验收

完成一次治理后重新运行脚本，并额外确认：

- 注册表中所有哈希重新计算一致；
- 五宿主没有悬空软链接；
- 新增公共 Skill 在 Claude、Qoder、WorkBuddy 的入口指向公共真源；
- Codex/Cursor 没有冗余用户级副本；
- 本轮测试、回滚和审查临时目录已经清除。

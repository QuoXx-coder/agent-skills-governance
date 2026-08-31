---
name: agent-skills-governance
description: 当用户有跨两个或更多 AI 智能体的 Skills，需要初始化或检查共享 Skill 真源、修复漂移或断开的条目、安全同步已批准的 Skills，或评估新安装的智能体能否接入共享 Skill 治理时使用。
---

# 多智能体 Skill 治理

把共享 Skill 当作只有唯一权威的资产，而不是在智能体之间复制的文件。公共真源通常位于 `~/.agents/skills`（Windows：`%USERPROFILE%\.agents\skills`）。发现与诊断默认只读；任何发现都不构成写入授权。

## 新手路径

当用户提供本 Skill 的路径或仓库地址时，用当前宿主的原生机制安装。随后，对「初始化 / 检查我的 Skill 治理」，先读 [首次上手说明](references/onboarding.md)，并运行只读的 `doctor` 命令。在请求任何注册、链接、复制、迁移或清理的批准之前，先展示它的状态卡。

优先使用 `uv` 自带的 Python；否则用 Python 3.9+（macOS/Linux 用 `python3`，Windows 用 `py -3`）。未经用户同意不安装运行时。

## 运营模型

- `direct`：宿主声明 `direct_source_root`；它必须是公共真源。不要创建重复的宿主目录。
- `symlink`：宿主入口指向公共真源。宿主和平台支持目录链接时优先使用。
- `managed_copy`：仅用于无法使用链接的宿主。副本携带 `.agent-skill-source.json` 并原子更新。
- 市场、内置、缓存和仅项目使用的 Skill 永远不会被自动收编。一个宿主的同名 Skill 只有一个权威。宿主拥有的权威需要带来源和理由的结构化例外。

面向用户的心智模型和冲突决策，读 [手册](references/handbook.md)。Profile 格式仅在评估新宿主时读 [profiles/README.md](profiles/README.md)。

## 命令

```bash
# 第一眼：只读状态卡，含候选与运行时证据
python3 scripts/governance.py doctor

# 详细只读操作
python3 scripts/governance.py discover
python3 scripts/governance.py audit --strict --format json

# 预览；仅在用户确认精确条目后加 --apply
python3 scripts/governance.py sync
python3 scripts/governance.py sync --apply
```

新安装使用两个本地文件：`~/.agents/governance.json`（宿主、插件记录、公共真源根）和 `~/.agents/skills.lock.json`（生成的 Skill 哈希）。用 `--governance` 和 `--lock` 同时传入。旧的 `~/.agents/skills-registry.json` 保持只读兼容；发现不得覆盖它。

在 `sync --apply` 之前，核心拒绝：不安全名称、缺失 `SKILL.md`、非法 frontmatter、真源/哈希漂移、未知目标、非法 direct 源。它绝不替换未知真实目录。清理、登记、迁移或 Profile 更新仍需显式确认。

## 验收

一次已批准的变更之后，先运行最小相关测试，再跑 `audit --strict`。有效结果必须：无哈希漂移、无断开的入口、无未批准的重复权威。不要仅仅因为发现了一个应用名或文件夹，就声称某个宿主已被治理。

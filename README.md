# Agent Skills Governance — 多智能体 Skill 治理工具

把每一份共享 Skill 放回唯一的家（真源），让每个已接入的 Agent 都通过受管入口读到它。
解决多 Agent（Claude Code / Codex / Cursor / Qoder / WorkBuddy…）之间技能复制、漂移、同名冲突的问题。

> 配套方法论见《多智能体 Skill 治理手册》：真源 vs 副本、三种入口模式、四张决策树。

## 快速开始（3 步）

需要 Python 3.9+，零第三方依赖。本地状态放在 `~/.agents/`（Windows：`%USERPROFILE%\.agents\`）。

```bash
# 1. 建两份本地状态文件（governance.json 声明宿主与公共根，skills.lock.json 记录技能哈希）
mkdir -p ~/.agents
cp templates/governance.json ~/.agents/governance.json
cp templates/skills.lock.json ~/.agents/skills.lock.json
# Windows PowerShell:
#   mkdir $env:USERPROFILE\.agents
#   copy templates\governance.json $env:USERPROFILE\.agents\governance.json
#   copy templates\skills.lock.json $env:USERPROFILE\.agents\skills.lock.json

# 2. 一键自检：审计 + 候选发现 + 下一步建议（只读）
python3 scripts/governance.py doctor --governance ~/.agents/governance.json --lock ~/.agents/skills.lock.json

# 3. 看机器上有哪些疑似宿主（只读，候选永远不是已接入宿主）
python3 scripts/governance.py discover --governance ~/.agents/governance.json --lock ~/.agents/skills.lock.json
```

之后把宿主登记进 `governance.json`、把技能登记进 `skills.lock.json`，再跑 `audit` 检查、`sync` 同步入口。

## 命令

| 命令 | 作用 |
| --- | --- |
| `doctor` | 一键自检：审计 + 候选发现 + 运行时信息（只读） |
| `discover` | 候选宿主发现（只读），候选永远不等于已接入宿主 |
| `audit` | 检查哈希、frontmatter、入口、残留、冲突（只读） |
| `sync` | 入口同步计划（默认干跑；`--apply` 才写盘，且先过 preflight） |
| `hash` | 计算一个真源目录的内容哈希 |

v2 状态由两个文件组成，必须成对传入：`--governance ~/.agents/governance.json --lock ~/.agents/skills.lock.json`。
旧格式 `~/.agents/skills-registry.json` 保持只读兼容（`--registry`），发现过程不会覆盖它。
机器可读输出：`doctor` / `audit` 加 `--format json`。

## 安全边界

- `sync --apply` 拒绝：非法名称、缺 SKILL.md、frontmatter 非法、哈希漂移、未登记宿主、非法 direct 源
- `direct` 宿主必须用 `direct_source_root` 指明公共真源
- `symlink` 首选；Windows 确认无链接权限才回退 `managed_copy`
- managed_copy 更新走临时目录 + 校验 + 失败回滚；**绝不覆盖未知真实目录**
- 市场/内置技能归宿主所有；同名冲突登记结构化 `host_exception`（kind/source/reason），不互相覆盖
- 宿主档案（profiles/）只是发现证据，不是登记授权；预置 claude-code / codex 档案，其余按官方文档自行核实

## 免责声明

本工具按作者自己的机器环境编写和验证（macOS + Claude Code / Codex / Cursor / Qoder / WorkBuddy 布局）。
其他平台与宿主布局可能需要自行调整路径与安装标记。作者不为你的环境负责——本工具是演示级治理，不是替你托管一切的商业软件。

## 测试

```bash
python3 tests/portable_governance_test.py
```

覆盖 Linux/macOS 软链接、Windows managed_copy、v2 direct、Profile 候选发现、preflight 拒绝不安全写入。

## License

MIT

# Agent Skills Governance

对多个本机智能体的 Skill 真源、注册表、软链接和配置漂移做只读巡检。

它适用于 Codex、Claude、Cursor、Qoder 和 WorkBuddy 的共享 Skill 治理：确认来源存在、frontmatter 合法、内容哈希一致、宿主入口正确，并报告断链、重复真实目录和临时残留。

## 特性

- 默认只读：报告问题不等于授权修复。
- 识别并尊重 Marketplace、内置能力等已登记的宿主例外。
- 机器可读 JSON 输出，适合 CI 或定期巡检。
- 不依赖第三方 Ruby gem。

## 要求

- Ruby 2.6 或更高版本。
- 一份 YAML 注册表；默认路径为 `~/.agents/skills-registry.yaml`。
- 受管公共 Skill 默认位于 `~/.agents/skills`。

克隆仓库后，可从任意目录运行脚本：

```bash
git clone https://github.com/QuoXx-coder/agent-skills-governance.git
cd agent-skills-governance
./scripts/audit-skills
```

将它安装为共享 Skill 时，建议把克隆目录作为 `~/.agents/skills/agent-skills-governance` 的真源，并在注册表中登记；本项目不会自动修改注册表或创建宿主软链接。

## 使用

```bash
# 人类可读报告
./scripts/audit-skills

# JSON 输出
./scripts/audit-skills --format json

# warning 或 error 时以非零状态退出
./scripts/audit-skills --strict

# 可选：额外用当前 Codex CLI 严格解析配置
./scripts/audit-skills --check-codex-config
```

可用 `--home`、`--registry`、`--canonical-root` 和 `--temp-root` 在测试或迁移时覆盖默认路径。运行 `./scripts/audit-skills --help` 查看完整参数。

## 隐私与安全边界

默认模式只读取注册表、受管 Skill 和五个用户级 Skill 根目录，不会删除、移动、覆盖或更新任何文件。

`--check-codex-config` 会启动当前 PATH 中的 Codex CLI 来严格读取配置；它不改写配置，但运行行为会受本机 Codex 配置影响。若不需要这项检查，请不要传入该参数。

## 测试

```bash
ruby tests/host_exception_duplicate_test.rb
```

## 许可证

[MIT](LICENSE)

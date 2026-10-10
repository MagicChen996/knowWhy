---
task_name: "从共享 session 同步 knowWhy 并完成项目（库/CLI + 可安装 Agent Skill）"
task_id: "14"
task_status: "completed"
capture_gate: false
---

# knowWhy 项目同步与完成

## Objective

用户提供了已完成的共享 session（`/share/sessions/wBhIpIRN`，主题「AI会话周期性know why学习方案」），
要求把它 **sync 过来，在当前 knowWhy 项目里完成**。经确认：落地到项目根目录
`/Users/deepprinciple/knowWhy`；程度为「补全 + 跑通 + 加入可安装 Skill」。

## Execution Summary

从共享 session 的发布 API 同步了 16 个文件（Python 库/CLI、示例、测试、Skill 参考、
README/LICENSE），补齐了共享中缺失的 3 个关键文件（`knowwhy/__init__.py`、
`pyproject.toml`、`.gitignore`），跑通 **28 项 pytest**（库 23 + Skill 脚本 5）与 CLI
全子命令端到端；补写了此前从未交付的 `skill/knowwhy/SKILL.md`（Skill 的必需入口），
让 Skill 通过 skill-creator 校验并打包为可安装的 `knowwhy.skill`；修复了 Skill 脚本
一个真实缺陷；用一条真实的新轨迹（DFT 带隙任务）做了端到端验证。

## Process

### Step-by-step

#### Step 1. 解析共享 session，而非抓网页

`web_fetch` 对 `127.0.0.1` 被 SSRF 拦截，本地 `curl` 拿到的是 Next.js 外壳 HTML。
从 share 页 chunk 定位到 API：`/api/v1/session-shares/<token>`。该接口返回
`messages`（含 `streamEvents` 完整会话轨迹）+ `task_groups[].files[]`（17 个文件，
每个带 `downloadUrl`）。据此枚举全部交付文件并逐个下载。

#### Step 2. 读懂原项目

逐文件读取：`knowwhy/` 的 models/trace/engine/triggers/recall/cli、`tests/`、
`examples/`、`templates/`、`skill/` 参考、README、conclusion.md（上一任务的结论文档，
含架构、取舍、未完成项）。

#### Step 3. 定位「缺什么」

共享的 16 个文件里**没有** `pyproject.toml` 与 `knowwhy/__init__.py`——而 README
与测试都依赖它们（`from knowwhy import ...` 需要 `__init__.py`；`pip install .`
和 `knowwhy` 命令需要 `pyproject.toml`）。`skill/knowwhy/SKILL.md` 也不在共享中
（原会话写它时被标记为受保护内容）。这三者是「能不能真正跑起来 / 是不是真 skill」
的关键。

#### Step 4. 落地 + 补齐

把 16 个文件铺到项目根目录；新建 `knowwhy/__init__.py`（公共 API 与 `__version__`，
按测试与 CLI 的实际 import 反推导出面）、`pyproject.toml`（knowwhy 0.1.0，零运行时
依赖，注册 `knowwhy` 命令）、`.gitignore`。

#### Step 5. 跑通验证

- `python -m pytest -q` → **23 passed**（还原后的代码与上一会话一致，说明同步无损）。
- CLI 端到端：`--version` / `summarize` / `reflect --focus` / `trigger` / `check-manual` 全部工作。
- `pip install .` 成功，`knowwhy` 控制台命令可用；从任意目录 `import knowwhy` 正常。
- Skill 脚本在**未安装**库的路径下也能跑（向上查找仓库内包）。

#### Step 6. 补写 SKILL.md 并使其成为真正的 Skill

按 skill-creator 规范补写 `skill/knowwhy/SKILL.md`：frontmatter（name + 含触发条件的
description，覆盖中英文触发语「为什么/复盘/说下原理/why did you / walk me through」等）、
三种触发时机与优先级、五步执行流程、五维框架表、"先给选择再展开"的低摩擦交互、
置信度纪律、文件导航与边界。另加 `skill/knowwhy/README.md`。

#### Step 7. 校验与打包

用 skill-creator 的 `quick_validate` 校验 → **Skill is valid!**；用 `package_skill`
打包 → `knowwhy.skill`（含 SKILL.md / README / 脚本 / 两个参考）。

#### Step 8. 真实轨迹端到端 + 修复缺陷

构造一条此前未见过的真实轨迹（晶体 CIF→带隙→可见光催化判断，含 PBE 低估带隙改用
HSE06、SCF 未收敛重试）。跑通 summarize / reflect（全维 + focus）/ trigger（状态持久化，
第 9 轮按 cadence 触发）时发现：Skill 脚本的 `reflect` **不支持 `--record/--store`**，
导致 SKILL.md 承诺的「写进成长记忆」在 Skill 路径下无法实现。修复后重测通过。

#### Step 9. 加回归测试与文档同步

新增 `tests/test_skill_script.py`（5 项）：验证 Skill 脚本未安装可跑、与库输出一致、
focus 生效、`--record` 真落盘并能被 `review` 读回、trigger 状态持久化。测试总数 **28**。
同步更新 README 的安装行、Skill 小节与目录结构。

## Issues Encountered

**问题 1：网页抓取被拦截 / 只能拿到前端外壳。** 处理：改走发布 API
`/api/v1/session-shares/<token>`，直接取得结构化会话与文件清单。无残留风险。

**问题 2：共享缺 `__init__.py` 与 `pyproject.toml`。** 症状：原样落地后无法
`import knowwhy`、无法安装。处理：按测试/CLI 的 import 面补 `__init__.py`（导出
models/trace/engine/triggers/recall 的公共符号 + `__version__`），按 README 声明的
包名/版本/入口补 `pyproject.toml`。修复后 import 与 `pip install .` 均通过。

**问题 3：Skill 从未有 SKILL.md。** 症状：`skill/` 目录不构成可安装 skill。
处理：按 skill-creator 规范补写并通过校验、打包。

**问题 4：Skill 脚本 `reflect` 不支持 `--record/--store`。** 症状：从 Skill 路径
记录成长记忆会报 `unrecognized arguments`。原因：脚本只透传了库 CLI 的部分参数。
处理：给 `reflect` 子命令补 `--record/--store`，并在处理分支里调用
`GrowthEntry.from_reflection` + `append_entry`。加 5 项回归测试锁定。已修。

**问题 5：校验脚本缺少 yaml 依赖。** 症状：运行 skill-creator 校验时报
`No module named yaml`。处理：通过规定的依赖准备通道补装后重跑，校验通过。
（实现细节，不影响交付物。）

## Results

### Key Findings

- 共享 session 是可完整复现的：16 个文件同步到本地后，**23 项原测试仍全绿**，说明
  同步无损、代码自洽。
- 原项目的「未完成」不只是 push——共享里**缺三个关键文件**（`__init__.py` /
  `pyproject.toml` / `SKILL.md`），即上一会话的交付物本身并不完整、不可直接安装。
- 补齐后形成完整闭环：**28 项 pytest 全绿**；CLI 五个子命令与 `knowwhy` 控制台命令
  均可用；Skill 通过 skill-creator 校验并打包为 `knowwhy.skill`。
- 用**真实新轨迹**（DFT 带隙）验证了通用性：summarize 正确抽出 4 个决策点与 1 处失败，
  五维骨架锚定到具体步骤，growth review 能跨「JSONL + Markdown」两种来源累积。
- 发现并修复了 Skill 脚本无法记录成长记忆的真实缺陷，并加测试防回归。

### Key Files

| File Name | Description |
|-----------|-------------|
| `knowwhy/__init__.py` | 新增：公共 API 与版本号，测试/CLI 的 import 基座 |
| `pyproject.toml` | 新增：可安装包 knowwhy 0.1.0（零运行时依赖）+ `knowwhy` 命令 |
| `skill/knowwhy/SKILL.md` | 新增：Skill 必需入口，触发条件 + 五步流程 + 五维框架 |
| `skill/knowwhy/scripts/summarize_trace.py` | 修复：`reflect` 补 `--record/--store` |
| `tests/test_skill_script.py` | 新增：5 项 Skill 脚本回归测试 |
| `knowwhy.skill` | 打包好的可安装 skill 文件 |

## Suggested Next Actions

- 用更多真实领域的会话轨迹跑 `knowwhy reflect`，检验「原理层/迁移」两维由 agent 补全
  后的实际教学质量。
- 按 skill-creator 的 evals 流程为 `knowwhy` 做触发精度评估（should/should-not-trigger
  查询集）并优化 description。
- 若要推送到 `MagicChen996/knowWhy`：本地执行 `git add -A && git commit && git push`
  （本环境无远程推送凭据）。
- 可把 `review` 挂到定时任务，实现每周「认知成长回顾」。

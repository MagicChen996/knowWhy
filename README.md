# knowWhy

> 让使用者在使用 AI 完成任务的同时，**周期性复盘「为什么每一步这样做」**，
> 把认知外包变成能力增长。

## 问题

AI / Agent / LLM 能完成越来越多使用者自己做不到的事。但结果拿到手之后，
使用者自身往往没有变强——这是**认知外包（cognitive offloading）**：
AI 交付的是 *what*，使用者需要的是 *why*。

knowWhy 在做完一个任务后插入一个**低摩擦的反思回合**，把刚刚真实发生的流程
拆成结构化的因果链，并把可迁移的经验沉淀到跨会话的成长记忆里。

## 核心纪律

反思对象永远是**本次任务里真实发生的事**，不是泛泛的科普。
任何解释都要能指回具体的 `step N` / 工具名 / 参数，并区分「事实」与「推断」。

## 架构

```
             ┌──────────────────── 上层：Agent Skill（何时/怎么用）────────────────────┐
             │  skill/knowwhy/SKILL.md  · 五维话术 · 触发时机 · 低摩擦呈现            │
             └───────────────────────────────┬───────────────────────────────────────┘
                                             │ 调用
┌─────────────── 底层：Python 库 / CLI（怎么算） ───────────────┐
│ trace.py    原始会话 → SessionTrace（JSONL / JSON / Markdown）│
│ engine.py   SessionTrace → 五维反思骨架（带置信度+来源）      │
│ triggers.py 触发策略：任务边界 / 每 N 轮 / 手动               │
│ recall.py   成长记忆：learned / stuck 的 JSONL 累积           │
│ cli.py      summarize · reflect · review · trigger            │
└──────────────────────────────────────────────────────────────┘
```

## 安装

```bash
pip install .          # 提供 `knowwhy` 命令
python -m pytest -q    # 28 项自测
```

## 快速上手（CLI）

```bash
# 1. 把会话轨迹压成紧凑摘要，喂给反思
knowwhy summarize examples/demo_session.jsonl

# 2. 生成五维复盘（Markdown / JSON；可只展开一个维度）
knowwhy reflect examples/demo_session.jsonl
knowwhy reflect examples/demo_session.jsonl --focus decisions --json

# 3. 触发策略：现在该不该复盘？
knowwhy trigger --state .knowwhy/state.json --task-ended --n-steps 6 --turn 12

# 4. 周期性成长回顾
knowwhy review --store .knowwhy/growth.jsonl
```

## 快速上手（库）

```python
from knowwhy import load_trace, summarize_trace, build_reflection

trace = load_trace("session.jsonl")
print(summarize_trace(trace))                 # 紧凑摘要
print(build_reflection(trace).to_markdown())  # 五维复盘
```

## 五维复盘框架

| 维度 | 回答什么 |
|---|---|
| 目标回溯 | 真正要解决什么问题？为什么是这个目标？判据是什么？ |
| 决策点 | 哪几步是真正的「选择」？依据什么？放弃了哪些备选？ |
| 原理层 | 每步背后的机制/公式/领域知识？为什么有效？何时失效？ |
| 证据链 | 结论从哪些数据/文献推出？哪步是事实、哪步是推断？ |
| 迁移 | 换一个问题哪部分能复用？还缺哪块能力？ |

## 触发策略（周期性）

三种触发，可组合，优先级 `manual > task_boundary > every_n_turns`：

- **任务边界**：多步任务刚完成/失败（≥3 步）→ 主动复盘邀请；
- **每 N 轮**：长会话里连续约 8 轮未复盘 → 轻量提醒（可「跳过」静默）；
- **手动**：用户说"讲讲为什么/复盘/explain your approach"→ 立即展开。

## 作为 Agent Skill 使用

`skill/knowwhy/` 是符合 agent-skill 规范的可安装 skill（已通过 skill-creator
校验并打包为 `knowwhy.skill`）。把它放进你的 agent 的 skills 目录即可；
它会在任务边界自动触发，并调用 `scripts/summarize_trace.py` 生成摘要与复盘骨架。

```bash
# 重新打包（改了 skill 之后）
python -m scripts.package_skill skill/knowwhy   # 需要 skill-creator 的脚本
```

## 目录结构

```
knowWhy/
├── knowwhy/            # Python 库（trace / engine / triggers / recall / cli）+ __init__.py
├── templates/          # 通用五维话术模板
├── examples/           # 示例轨迹（JSONL + Markdown）
├── tests/              # pytest 自测（库 23 项 + Skill 脚本 5 项）
├── skill/knowwhy/      # 可安装 Agent Skill
│   ├── SKILL.md
│   ├── README.md
│   ├── scripts/summarize_trace.py
│   └── references/     # 话术模板 + 轨迹格式规范
├── knowwhy.skill       # 打包好的可安装 skill 文件
├── pyproject.toml
└── README.md
```

## 设计取舍

- **为什么 skill + 库，而不是二选一**：库承载"怎么算"（可测试、可复用、可被任何
  runtime 调用），Skill 承载"何时触发、怎么讲给用户听"。方法论才是可迁移资产，
  所以 Skill 是主体，库是它的手脚。
- **为什么骨架先行**：无结构地让 LLM"解释一下"，会漂移成无关的教科书段落。
  用固定五维 + 轨迹锚点约束它，才能保证反思扣住本次任务。
- **为什么标置信度**：反思本身也会幻觉。区分 fact / inference，避免用错误知识
  训练使用者。

## License

MIT

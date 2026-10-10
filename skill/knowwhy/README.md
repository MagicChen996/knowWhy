# knowwhy (Agent Skill)

让使用者在使用 AI 完成任务的同时，**周期性复盘「为什么每一步这样做」**。

这个目录是一个符合 agent-skill 规范的可安装 skill。把它放进你的 agent 的
skills 目录即可；它会在任务边界自动触发，并调用 `scripts/summarize_trace.py`
生成摘要与复盘骨架。

## 结构

```
skill/knowwhy/
├── SKILL.md                        # skill 入口：何时触发、怎么讲、五维框架
├── scripts/summarize_trace.py      # summarize / reflect / trigger / review
└── references/
    ├── reflection_template.md      # 五维话术模板 + 输出格式 + 反面样例
    └── trace_formats.md            # 三种轨迹输入格式规范
```

## 依赖

**运行时零依赖**，只需 Python 3.9+。脚本会自动向上查找仓库里的 `knowwhy` 包，
所以在 checkout 里能直接跑；若已在仓库根目录 `pip install .`，也可用 `knowwhy` 命令。

## 快速自测

```bash
# 在仓库根目录执行
python skill/knowwhy/scripts/summarize_trace.py summarize examples/demo_session.jsonl
python skill/knowwhy/scripts/summarize_trace.py reflect   examples/demo_conclusion.md
python skill/knowwhy/scripts/summarize_trace.py trigger   --task-ended --n-steps 6 --turn 6
```

## 与其他 skill 的边界

knowwhy 只负责「把已经发生的事讲明白」。它不做文献检索、不做领域计算——
那些交给对应的领域 skill；knowwhy 在任务**之后**运行。

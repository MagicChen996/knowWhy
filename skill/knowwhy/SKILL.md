---
name: knowwhy
description: >-
  Periodic know-why reflection on a task you just finished, so the person who
  watched the AI do the work actually learns from it instead of just receiving
  the result. Use this skill whenever a multi-step task, analysis, experiment,
  calculation, or investigation has just completed or failed and the user might
  benefit from understanding *why* each step was taken — including when the user
  says things like "为什么这么做", "讲讲为什么", "复盘", "说下原理", "know why",
  "explain your approach", "walk me through", or "how did you decide". Also use
  it proactively right after closing a task with several steps, on a long
  session that has gone many turns without reflection, or whenever someone wants
  to review what they have learned across recent sessions. This skill turns the
  real execution trace into a structured 5-dimension reflection and records the
  user's growth; it is not a generic explainer and must never drift into
  textbook talk detached from what actually happened.
---

# knowWhy — 让「用过 AI」变成「学会了」

## 这个 skill 解决什么问题

AI / Agent 能完成越来越多使用者自己做不到的事。但结果拿到手之后，使用者本身
往往没有变强——这是**认知外包（cognitive offloading）**：AI 交付的是 *what*，
使用者需要的是 *why*。

这个 skill 在任务结束时插入一个**低摩擦的反思回合**：把刚刚真实发生的流程拆成
结构化的因果链，讲清每一步「为什么这样做、依据什么、放弃了什么」，并把可迁移的
经验沉淀到跨会话的成长记忆里。

**核心纪律（最重要的一条）：反思对象永远是「本次任务里真实发生的事」，不是泛泛
的科普。** 任何解释都要能指回具体的 step 序号 / 工具名 / 参数，并区分「轨迹里观察
到的事实」与「推断」。脱离轨迹的解释 = 跑题。

---

## 何时触发

三种触发，优先级 `manual > task_boundary > every_n_turns`。用 `scripts/summarize_trace.py`
的 `trigger` 子命令判断，它会读写一个 JSON 状态文件，这样计数器能跨轮次保留。

| 时机 | reason | 你要做的 |
|---|---|---|
| 用户明确要求（"讲讲为什么/复盘/为什么选 X"） | `manual` | 立即展开，不啰嗦 |
| 一个 ≥3 步的任务刚完成/失败 | `task_boundary` | 主动邀请，给「展开 / 跳过」选择 |
| 连续约 8 轮没有复盘 | `every_n_turns` | 轻量提醒，允许「跳过」 |

判断当前该不该复盘：

```bash
python scripts/summarize_trace.py trigger \
  --state .knowwhy/state.json \
  --task-ended --n-steps 6 --turn 12
```

输出 `{"fire": true, "reason": "task_boundary", "message": "..."}`。`fire=false` 就什么都别做，
不要为了触发而触发。用户回「跳过」时，用 `snooze()`（或 `--user-text "跳过"` 配合状态）静默
一段时间，不要反复打扰。

---

## 执行流程

### 第 1 步：拿到本次任务的真实轨迹

反思必须有素材，否则就是编故事。按优先级取：

1. **如果 agent 运行环境里有会话轨迹**（工具调用链、参数、中间结果），先把它整理成
   JSONL（见 `references/trace_formats.md`），**在每个真正的「选择」处补上 `rationale`
   和 `alternatives`**——这两项决定了整份复盘的质量。
2. **如果没有现成轨迹，但有本次任务的结论文档**（如 `task_conclusion.md`），直接把它
   喂进去，解析器会自动把「因为 / 而非 / 之所以 / 选择」这类行提升为 rationale。
3. **如果两者都没有**，先问用户一句话：本次任务的关键选择是哪几个、当时为什么那么选。
   不要凭记忆编造轨迹。

### 第 2 步：压成紧凑摘要（这一步喂给反思）

```bash
python scripts/summarize_trace.py summarize <trace 文件>
```

得到包含 `goal / n_steps / tool_sequence / decision_points / failures` 的 JSON。这是反思的
锚点——`decision_points` 就是你要重点讲的「选择」，「failures」是最有教学价值的节点。

### 第 3 步：生成五维骨架

```bash
python scripts/summarize_trace.py reflect <trace 文件>            # Markdown，全维
python scripts/summarize_trace.py reflect <trace 文件> --focus decisions   # 只展开一维
python scripts/summarize_trace.py reflect <trace 文件> --json     # 结构化
```

骨架给了你五个维度的**问题和轨迹锚点**，但「原理层」和「迁移」两维库只能给低置信度
占位——**这两维的高质量内容必须由你结合领域知识补全**，这正是这个 skill 存在的意义。

### 第 4 步：把骨架讲成给用户听的复盘

**先判断用户是想「快速看一眼」还是「认真学一遍」。** 默认走低摩擦路线：

> 任务完成了 ✅ 花两分钟复盘一下这套流程，下次你自己也能走一遍——
> ① 我为什么先查文献再计算？（决策点）
> ② 中间这个参数为什么这样设？（原理层）
> ③ 下次你自己做，从哪一步开始？（迁移）
> 要展开哪一条？还是先跳过？

用户选一条，你**只展开那一条**（用 `--focus`），讲透再问要不要继续。不要一次倾倒
五段长文——那是让人放弃的最快方式。

把每个维度讲成什么样，看 `references/reflection_template.md`；里面还给了**反面样例**
（"DFT 更准"这种脱离任务的科普）——务必避免。

### 第 5 步：写进成长记忆

每完成一次有实质内容的复盘，把它记下来，供日后回顾（"上次你搞懂了 X，这次遇到的是
它的近亲"）：

```bash
python scripts/summarize_trace.py reflect <trace 文件> --record --store .knowwhy/growth.jsonl
python scripts/summarize_trace.py review --store .knowwhy/growth.jsonl   # 周期性成长回顾
```

周期性的「本周认知回顾」用 `review` 输出，适合挂在定时任务里。

---

## 五维框架（讲什么）

| 维度 | 回答什么 | 好的输出长什么样 |
|---|---|---|
| **目标回溯** | 真正要解决什么问题？判据是什么？ | 点出「表面请求」和「真实目标」的差距 |
| **决策点** | 哪几步是真正的选择？依据？放弃了什么？ | `**选择 X**：做了什么 → 依据 → 放弃的替代` |
| **原理层** | 机制/公式/领域知识？为什么有效？何时失效？ | **必须标来源**，无来源标低置信度 |
| **证据链** | 结论从哪推出？哪步是事实、哪步是推断？ | 拆成证据节点，明确 fact vs inference |
| **迁移** | 换问题哪部分能复用？还缺哪块能力？ | 1-3 条可迁移经验 + 适用边界 |

关于**置信度与来源**：反思本身也会幻觉。区分「轨迹里观察到的事实」和「推断/领域
知识」，凡是没有来源的机制解释标低置信度，宁可说"这点我不确定"。用错误知识训练
使用者，比不反思更糟。

---

## 文件导航

- `scripts/summarize_trace.py` — 摘要 / 五维骨架 / 触发判断 / 成长回顾，四个子命令。
  在仓库里可直接跑（会自动找到未安装的 `knowwhy` 包）；`pip install .` 后也可用
  `knowwhy` 命令。
- `references/reflection_template.md` — 五维话术模板、每维输出格式、反面样例。
  **讲给用户听之前先读它。**
- `references/trace_formats.md` — 三种轨迹输入格式（JSONL / JSON / Markdown）与字段
  规范。用户要提供或你要生成轨迹时读它。

## 边界

- 这是**通用**反思 skill，不绑定领域。科研、工程、数据分析都适用。
- 不做文献检索、不做领域计算——那些用别的 skill；这个 skill 只负责「把已经发生的
  事讲明白」。
- 如果本次任务只有 1-2 步、没有真正的选择，不要硬凑一场复盘。

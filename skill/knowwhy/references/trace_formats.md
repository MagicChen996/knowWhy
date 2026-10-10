# 轨迹格式规范（knowWhy 输入）

knowWhy 接受的轨迹必须能被归一到 `SessionTrace`（见 `knowwhy/models.py`）。
三种格式任选其一，解析是宽松的、自动识别的。

**所有格式的共同成功要素：给真正的「选择」补上 `rationale` 与 `alternatives`。**
这两项决定了「决策点」维度的质量，是整套复盘的地基。

---

## 1. JSONL（推荐，agent 边跑边记）

每行一个 JSON 对象；第一行可以是 `{"kind": "session_meta", ...}`。

```jsonl
{"kind": "session_meta", "session_id": "s1", "task_name": "预测溶解度", "goal": "判断是否值得做实验", "final_outcome": "给出区间与建议"}
{"kind": "tool_call", "name": "web_search", "summary": "查已知溶解度", "rationale": "先看有无实测，有就不用算", "alternatives": ["直接算", "查内部库"], "success": true}
{"kind": "tool_call", "name": "reactify", "summary": "构象采样后重算", "rationale": "首算异常，怀疑构象没采全", "success": true}
```

字段：

| 字段 | 说明 |
|---|---|
| `kind` | `session_meta` / `tool_call` / `tool_result` / `assistant_message` / `user_message` / `note`（别名 `type`/`role` 也会被识别） |
| `name` | 工具或 skill 名（别名 `tool`/`skill`） |
| `summary` | 一句话描述（别名 `content`/`text`） |
| `rationale` | **关键**，为什么这么做（别名 `reason`/`why`） |
| `alternatives` | **关键**，考虑过但放弃的备选（别名 `options`/`considered`） |
| `inputs` | 参数（别名 `args`/`arguments`） |
| `success` | 布尔；若给了 `error` 字段会自动判 `false` |

## 2. JSON（一次性导出）

```json
{
  "session_id": "s1",
  "task_name": "整理实验数据",
  "goal": "合并三批数据并找异常",
  "final_outcome": "输出对比图 + 异常说明",
  "steps": [
    {"kind": "note", "summary": "先对齐列名", "rationale": "之前被列名不一致坑过"},
    {"kind": "note", "summary": "用中位数汇总", "rationale": "有离群点，均值会被带偏", "alternatives": ["均值", "截尾均值"]}
  ]
}
```

## 3. Markdown（已有结论文档，零改造）

像 `task_conclusion.md` 那样直接喂。解析规则：

- `# 目标 / Goal / 任务` 开头的标题 → `goal`；
- `# 结果 / 结论 / Outcome` 开头的标题 → `final_outcome`；
- 编号列表 / 项目符号行 → 步骤；
- **含「因为 / 为了 / 避免 / 而非 / 之所以 / 选择 / because / instead of」等词的行 → 自动提升为 `rationale`**，从而成为决策点。

```markdown
## 目标
合并三批实验数据，找出异常批次
## 过程
1. 先检查列名是否一致 —— 因为之前被列名坑过
2. 用中位数而非均值汇总 —— 因为有离群点
## 结果
输出对比图 + 异常批次说明
```

---

## 归一化后会得到什么

```python
SessionTrace(
    goal=..., final_outcome=..., steps=[TraceStep, ...]
)
# trace.decision_points()  -> 带 rationale 或 alternatives 的步骤（复盘的重点）
# trace.tool_calls()       -> kind == "tool_call" 的步骤
# trace.failures()         -> success is False 的步骤
```

命令行自测：

```bash
python -m knowwhy.cli summarize examples/demo_session.jsonl
python -m knowwhy.cli reflect   examples/demo_conclusion.md
```

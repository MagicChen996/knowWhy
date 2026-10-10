"""HTML report: turn a trace + reflection into a self-contained page.

Everything else in knowWhy produces *data* (JSON) or *text for the agent*
(Markdown). Neither is what a person actually wants after watching an AI do a
task: they want to **see the run** — what happened, in order, and why each step
was taken. This module renders exactly that, as one standalone HTML file that
opens in a browser with no server and no network.

Design decisions that matter:

1. **Timeline first.** The spine of the report is the ordered list of steps the
   agent actually took. Reflections without a timeline are abstract; a timeline
   is what makes the user go "ah, *that* is what happened".

2. **Skeleton, not fabrication.** The library fills in everything it can prove
   from the trace (what was called, what failed, what the agent itself said).
   For "why / principle" it can only supply *scaffolding* — the concrete
   question to answer plus the trace anchor — because the library does not know
   the domain. Those slots render as clearly-marked prompts, never as invented
   explanations. An agent (or the user) fills them in.

3. **No network, no build step.** All CSS and JS are inlined; fonts are system
   fonts. The file works offline, over `file://`, and can be committed to a repo
   or emailed without breaking.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Optional

from .models import DIMENSION_LABELS_ZH, Reflection, SessionTrace, TraceStep

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

_CONFIDENCE_LABEL = {
    "high": "高置信",
    "medium": "中置信",
    "low": "低置信 · 待补全",
}

# Steps whose kind groups under the same visual family.
_KIND_LABEL = {
    "tool_call": "工具调用",
    "tool_result": "工具返回",
    "assistant_message": "助手说明",
    "user_message": "用户",
    "note": "记录",
}


def _e(text: Any) -> str:
    """Escape for HTML text context."""
    return html.escape(str(text if text is not None else ""), quote=True)


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    text = text or ""
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip(), True


# --------------------------------------------------------------------------- #
# Step -> structured card data
# --------------------------------------------------------------------------- #


def _step_card(step: TraceStep, reflection: Optional[Reflection]) -> dict[str, Any]:
    """Build the display model for one timeline entry.

    `why` and `principle` are the two fields a person most wants. The trace
    almost never carries them, so we surface:
      * `why` — the agent's own rationale if recorded, else the observable
        evidence the capture layer inferred ("failed, then switched tools").
      * `principle` — left as a scaffold prompt tied to this step, because the
        library cannot know the domain mechanism.
    """
    out_preview, out_truncated = _truncate(step.outputs_summary or "", 600)

    if step.kind == "tool_call":
        why = step.rationale or ""
        alternatives = step.alternatives or []
        # The principle slot is deliberately a *question*, not an answer.
        if step.name:
            principle_prompt = (
                f"「{step.name}」这一步背后的机制 / 原理是什么？"
                f"为什么这样做有效？它的适用前提或失效场景是什么？"
            )
        else:
            principle_prompt = "这一步背后的机制 / 原理是什么？"
    else:
        why = ""
        alternatives = []
        principle_prompt = ""

    status = "unknown"
    if step.success is True:
        status = "ok"
    elif step.success is False:
        status = "fail"

    return {
        "index": step.index,
        "kind": step.kind,
        "kind_label": _KIND_LABEL.get(step.kind, step.kind),
        "name": step.name or "",
        "summary": step.summary or "",
        "why": why,
        "why_is_inferred": why.startswith("[观察到的线索]"),
        "alternatives": alternatives,
        "principle_prompt": principle_prompt,
        "inputs": step.inputs or {},
        "outputs": out_preview,
        "outputs_truncated": out_truncated,
        "status": status,
    }


def _steps_payload(trace: SessionTrace, reflection: Optional[Reflection]) -> list[dict[str, Any]]:
    return [_step_card(s, reflection) for s in trace.steps]


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #

_CSS = """
:root{
  --bg:#f6f7f9; --panel:#ffffff; --ink:#0f172a; --muted:#64748b; --line:#e2e8f0;
  --accent:#4f46e5; --accent-soft:#eef2ff;
  --ok:#10b981; --ok-soft:#ecfdf5;
  --fail:#ef4444; --fail-soft:#fef2f2;
  --warn:#f59e0b; --warn-soft:#fffbeb;
  --radius:14px;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#0b1120; --panel:#111a2e; --ink:#e8eefc; --muted:#8ea0bd; --line:#22304a;
    --accent:#8b93ff; --accent-soft:#1a2244;
    --ok:#34d399; --ok-soft:#0f2a22;
    --fail:#f87171; --fail-soft:#2a1416;
    --warn:#fbbf24; --warn-soft:#2a2210;
  }
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
    "Hiragino Sans GB","Microsoft YaHei",sans-serif;
  line-height:1.65; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1000px;margin:0 auto;padding:40px 24px 96px}
a{color:var(--accent)}
code,.mono{font-family:"SF Mono",Menlo,Consolas,"Liberation Mono",monospace}

header.hero{margin-bottom:32px}
.eyebrow{
  display:inline-block;font-size:12px;font-weight:700;letter-spacing:.14em;
  text-transform:uppercase;color:var(--accent);background:var(--accent-soft);
  padding:5px 11px;border-radius:999px;
}
h1{font-size:29px;line-height:1.3;margin:16px 0 8px;letter-spacing:-.01em}
.goal{color:var(--muted);font-size:15px;margin:0 0 18px;max-width:70ch}
.meta{display:flex;flex-wrap:wrap;gap:8px}
.chip{
  font-size:12.5px;color:var(--muted);background:var(--panel);
  border:1px solid var(--line);border-radius:999px;padding:4px 12px;
}
.chip b{color:var(--ink);font-weight:600}

/* summary strip */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:26px 0 34px}
.stat{
  background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px;
}
.stat .n{font-size:26px;font-weight:700;letter-spacing:-.02em}
.stat .k{font-size:12.5px;color:var(--muted);margin-top:2px}
.stat.fail .n{color:var(--fail)}

h2{
  font-size:19px;margin:44px 0 6px;padding-bottom:10px;
  border-bottom:1px solid var(--line);
}
h2 .sub{font-size:13px;font-weight:400;color:var(--muted);margin-left:10px}

/* timeline */
.timeline{position:relative;margin-top:26px}
.timeline::before{
  content:"";position:absolute;left:15px;top:6px;bottom:6px;width:2px;
  background:linear-gradient(var(--line),var(--line));
}
.step{position:relative;padding:0 0 14px 46px}
.dot{
  position:absolute;left:8px;top:16px;width:16px;height:16px;border-radius:50%;
  background:var(--panel);border:2px solid var(--muted);z-index:1;
}
.step[data-status="ok"] .dot{border-color:var(--ok);background:var(--ok)}
.step[data-status="fail"] .dot{border-color:var(--fail);background:var(--fail)}
.step[data-kind="assistant_message"] .dot{border-color:var(--accent);background:var(--panel)}

details.card{
  background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  overflow:hidden;
}
.step[data-status="fail"] details.card{border-color:color-mix(in srgb,var(--fail) 45%,var(--line))}
details.card>summary{
  cursor:pointer;list-style:none;padding:13px 16px;display:flex;gap:11px;
  align-items:baseline;flex-wrap:wrap;
}
details.card>summary::-webkit-details-marker{display:none}
details.card>summary:hover{background:color-mix(in srgb,var(--accent) 4%,transparent)}
.idx{font-size:12px;font-weight:700;color:var(--muted);font-variant-numeric:tabular-nums;min-width:24px}
.badge{
  font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:6px;
  background:var(--accent-soft);color:var(--accent);white-space:nowrap;
}
.badge.k{background:color-mix(in srgb,var(--muted) 14%,transparent);color:var(--muted)}
.badge.fail{background:var(--fail-soft);color:var(--fail)}
.headline{flex:1 1 260px;min-width:0;font-size:14.5px}
.headline .tname{font-weight:600}
.headline .targ{color:var(--muted)}
.chev{color:var(--muted);font-size:12px;transition:transform .18s ease}
details[open]>summary .chev{transform:rotate(90deg)}

.body{padding:2px 16px 18px;border-top:1px solid var(--line)}
.field{margin-top:14px}
.field .lab{
  font-size:11.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  color:var(--muted);margin-bottom:5px;display:flex;align-items:center;gap:7px;
}
.field p{margin:0;font-size:14px}
.pill{font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:999px;letter-spacing:.04em}
.pill.fact{background:var(--ok-soft);color:var(--ok)}
.pill.infer{background:var(--warn-soft);color:var(--warn)}
.pill.todo{background:var(--accent-soft);color:var(--accent)}
.why-inferred{color:var(--ink)}
.answers{margin:6px 0 0;padding-left:18px;font-size:14px}
.answers li{margin:2px 0}
pre{
  margin:0;background:color-mix(in srgb,var(--muted) 9%,transparent);
  border:1px solid var(--line);border-radius:9px;padding:11px 13px;
  overflow-x:auto;font-size:12.5px;line-height:1.55;white-space:pre-wrap;word-break:break-word;
}
.scaffold{
  border-left:3px solid var(--accent);background:var(--accent-soft);
  border-radius:0 9px 9px 0;padding:11px 14px;font-size:13.5px;color:var(--ink);
}
.scaffold .q{color:var(--muted);font-size:12px;margin-top:5px}

/* dimension grid */
.dims{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-top:22px}
.dim{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:17px 18px}
.dim h3{margin:0 0 4px;font-size:15.5px;display:flex;align-items:center;gap:9px}
.dim .num{
  width:22px;height:22px;border-radius:7px;background:var(--accent);color:#fff;
  font-size:12px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;
}
.dim .ans{margin:9px 0 0;font-size:13.5px;white-space:pre-wrap}
.dim .qlist{margin:9px 0 0;padding-left:17px;font-size:12.5px;color:var(--muted)}
.dim .conf{margin-top:11px;font-size:11.5px;color:var(--muted)}

.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-top:18px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px}
.panel h3{margin:0 0 9px;font-size:14px}
.panel ul{margin:0;padding-left:18px;font-size:13.5px}
.panel li{margin:4px 0}
.panel.learned{border-top:3px solid var(--ok)}
.panel.stuck{border-top:3px solid var(--warn)}

footer{margin-top:56px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px}
.empty{color:var(--muted);font-size:13.5px;font-style:italic}

@media (max-width:620px){
  .wrap{padding:26px 16px 72px}
  h1{font-size:23px}
  .timeline::before{left:11px}
  .step{padding-left:38px}
  .dot{left:4px}
}
"""


def _render_step(card: dict[str, Any]) -> str:
    """One timeline entry as a collapsible <details> card."""
    status = card["status"]
    kind = card["kind"]
    idx = card["index"]
    name = card["name"]
    summary = card["summary"] or ""

    if kind == "tool_call":
        headline = f'<span class="tname">{_e(name)}</span>'
        if summary:
            headline += f' <span class="targ">· {_e(summary)}</span>'
        badge = f'<span class="badge k">{_e(card["kind_label"])}</span>'
    else:
        headline = _e(summary) or f'<span class="targ">{_e(card["kind_label"])}</span>'
        badge = f'<span class="badge k">{_e(card["kind_label"])}</span>'

    if status == "fail":
        badge += ' <span class="badge fail">失败 / 被拦</span>'

    # -- body sections, in the order a learner wants them ------------------ #
    body: list[str] = []

    if card["why"]:
        if card["why_is_inferred"]:
            body.append(
                '<div class="field"><div class="lab">为什么这么做 '
                '<span class="pill infer">推断</span></div>'
                f'<p class="why-inferred">{_e(card["why"])}</p></div>'
            )
        else:
            body.append(
                '<div class="field"><div class="lab">为什么这么做 '
                '<span class="pill fact">agent 记录</span></div>'
                f'<p>{_e(card["why"])}</p></div>'
            )

    if card["alternatives"]:
        items = "".join(f"<li>{_e(a)}</li>" for a in card["alternatives"])
        body.append(
            '<div class="field"><div class="lab">考虑过的备选</div>'
            f'<ul class="answers">{items}</ul></div>'
        )

    if card["principle_prompt"]:
        body.append(
            '<div class="field"><div class="lab">原理 / 知识点 '
            '<span class="pill todo">待补全</span></div>'
            f'<div class="scaffold">{_e(card["principle_prompt"])}'
            '<div class="q">这一栏由 agent 结合领域知识填写，库不编造；'
            "填完后它就是这次任务最值得带走的知识点。</div></div></div>"
        )

    if card["inputs"]:
        payload = json.dumps(card["inputs"], ensure_ascii=False, indent=2)
        body.append(
            '<div class="field"><div class="lab">参数</div>'
            f"<pre>{_e(payload)}</pre></div>"
        )

    if card["outputs"]:
        more = " …（已截断）" if card["outputs_truncated"] else ""
        body.append(
            '<div class="field"><div class="lab">返回</div>'
            f"<pre>{_e(card['outputs'])}{more}</pre></div>"
        )

    if not body:
        body.append('<div class="empty">这一步没有更多可展开的细节。</div>')

    return (
        f'<div class="step" data-status="{_e(status)}" data-kind="{_e(kind)}">'
        f'<span class="dot"></span>'
        f'<details class="card"><summary>'
        f'<span class="idx">#{idx + 1}</span>{badge}'
        f'<span class="headline">{headline}</span>'
        f'<span class="chev">▶</span>'
        f"</summary><div class=\"body\">{''.join(body)}</div></details></div>"
    )


def _render_dimension(d: Any, num: int) -> str:
    conf = _CONFIDENCE_LABEL.get(d.confidence, d.confidence)
    parts = [
        '<div class="dim">',
        f'<h3><span class="num">{num}</span>{_e(d.title)}</h3>',
    ]
    if d.answer:
        parts.append(f'<p class="ans">{_e(d.answer)}</p>')
    if d.questions:
        qs = "".join(f"<li>{_e(q)}</li>" for q in d.questions)
        parts.append(f'<ul class="qlist">{qs}</ul>')
    src = d.source or "推断"
    parts.append(f'<div class="conf">置信度：{_e(conf)} · 依据：{_e(src)}</div>')
    parts.append("</div>")
    return "".join(parts)


def render_report_html(
    trace: SessionTrace,
    reflection: Optional[Reflection] = None,
    *,
    title: str = "Know-Why 复盘",
) -> str:
    """Render a full, standalone HTML report for one session."""
    cards = [_step_card(s, reflection) for s in trace.steps]

    n_tools = len(trace.tool_calls())
    n_fail = len(trace.failures())
    n_dec = len(trace.decision_points())

    chips = [
        f'<span class="chip">共 <b>{len(trace.steps)}</b> 步</span>',
        f'<span class="chip">工具调用 <b>{n_tools}</b></span>',
        f'<span class="chip">决策点 <b>{n_dec}</b></span>',
        f'<span class="chip">失败 <b>{n_fail}</b></span>',
    ]
    m = trace.metadata or {}
    if m.get("model"):
        chips.append(f'<span class="chip">模型 <b>{_e(m["model"])}</b></span>')
    if m.get("total_turns"):
        chips.append(f'<span class="chip">轮次 <b>{_e(m["total_turns"])}</b></span>')
    if trace.source_format:
        chips.append(f'<span class="chip">来源 <b>{_e(trace.source_format)}</b></span>')

    stats = f"""
    <div class="stats">
      <div class="stat"><div class="n">{len(trace.steps)}</div><div class="k">执行步数</div></div>
      <div class="stat"><div class="n">{n_tools}</div><div class="k">工具调用</div></div>
      <div class="stat"><div class="n">{n_dec}</div><div class="k">决策点</div></div>
      <div class="stat{' fail' if n_fail else ''}"><div class="n">{n_fail}</div><div class="k">失败 / 回退</div></div>
    </div>
    """

    timeline = (
        '<div class="timeline">'
        + "".join(_render_step(c) for c in cards)
        + "</div>"
    )

    # reflection section (optional)
    dims_html = ""
    if reflection and reflection.dimensions:
        dims = "".join(
            _render_dimension(d, i + 1) for i, d in enumerate(reflection.dimensions)
        )
        dims_html = (
            '<h2>五维复盘<span class="sub">换个角度理解这次任务</span></h2>'
            f'<div class="dims">{dims}</div>'
        )

    panels_html = ""
    if reflection and (reflection.learned or reflection.stuck):
        p = []
        if reflection.learned:
            items = "".join(f"<li>{_e(x)}</li>" for x in reflection.learned)
            p.append(
                f'<div class="panel learned"><h3>✅ 你这次可以带走的</h3><ul>{items}</ul></div>'
            )
        if reflection.stuck:
            items = "".join(f"<li>{_e(x)}</li>" for x in reflection.stuck)
            p.append(
                f'<div class="panel stuck"><h3>🔎 仍待弄清</h3><ul>{items}</ul></div>'
            )
        panels_html = f'<div class="cols">{"".join(p)}</div>'

    goal = trace.goal or "（未记录目标）"
    outcome = trace.final_outcome or ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <span class="eyebrow">knowWhy · 执行复盘</span>
    <h1>{_e(trace.task_name or title)}</h1>
    <p class="goal">{_e(goal)}</p>
    <div class="meta">{''.join(chips)}</div>
  </header>

  {stats}

  <h2>任务时间线<span class="sub">点开任意一步，看它做了什么、为什么、背后原理</span></h2>
  {timeline}

  {dims_html}
  {panels_html}

  <footer>
    由 knowWhy 生成 · 时间线与「为什么」来自真实执行轨迹；标
    <span class="pill infer">推断</span> 的是从轨迹观察到的线索而非 agent 亲述；
    标 <span class="pill todo">待补全</span> 的原理栏由 agent 结合领域知识填写。
    {f'<br>最终结果：{_e(outcome[:300])}' if outcome else ''}
  </footer>
</div>
</body>
</html>
"""


def write_report(
    trace: SessionTrace,
    reflection: Optional[Reflection],
    out_path: str | Path,
    *,
    title: str = "Know-Why 复盘",
) -> Path:
    """Render and write the HTML report; returns the resolved path."""
    p = Path(out_path)
    if p.parent and str(p.parent) not in ("", "."):
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_report_html(trace, reflection, title=title), encoding="utf-8")
    return p

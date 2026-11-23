from .models import MeetingMinutes


def cell(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|").replace("\n", "<br>")


def render_minutes(minutes: MeetingMinutes) -> str:
    lines = [f"# {cell(minutes.title)}", "", f"- 会议日期：{cell(minutes.meeting_date)}",
             f"- 参会人：{cell('、'.join(minutes.participants) or '待定')}", ""]
    for heading, items in [("议题小结", minutes.topics), ("决策", minutes.decisions)]:
        lines += [f"## {heading}", ""]
        lines += [f"- {cell(i.text)}（依据：{i.source_ref}）" for i in items] or ["原文未明确列出。"]
        lines += [""]
    lines += ["## 待办", "", "| 负责人 | 事项 | 期限 | 状态 | 原文依据 |", "|---|---|---|---|---|"]
    lines += [f"| {cell(a.owner)} | {cell(a.text)} | {cell(a.due_text)} | {a.status} | {a.source_ref}：{cell(a.source_text)} |" for a in minutes.actions]
    if not minutes.actions:
        lines += ["| — | 原文未明确列出 | — | — | — |"]
    lines += [""]
    for heading, items in [("未决问题", minutes.unresolved), ("其他记录", minutes.other_notes)]:
        lines += [f"## {heading}", ""]
        lines += [f"- {cell(i.text)}（依据：{i.source_ref}）" for i in items] or ["原文未明确列出。"]
        lines += [""]
    return "\n".join(lines)

import json
import re
from datetime import date, timedelta

from .models import ActionGroup, MeetingMinutes, Merged, MergedAction
from .parser import NotesError, iso_date
from .render import cell


def resolve_due(due_text: str, meeting_date: str) -> str:
    absolute = iso_date(due_text)
    if absolute:
        return absolute
    base = iso_date(meeting_date)
    if not base:
        return "待定"
    day = date.fromisoformat(base)
    relative = re.fullmatch(r"(今天|明天|后天)(?:之前|以前|前|内|截止)?", due_text)
    if relative:
        return (day + timedelta(days={"今天": 0, "明天": 1, "后天": 2}[relative[1]])).isoformat()
    week = re.fullmatch(r"(下下|下|本|这)?(?:周|星期)([一二三四五六日天])(?:之前|以前|前|内|截止)?", due_text)
    if week:
        offset = {None: 0, "本": 0, "这": 0, "下": 7, "下下": 14}[week[1]]
        weekday = "一二三四五六日".find(week[2].replace("天", "日"))
        return (day - timedelta(days=day.weekday()) + timedelta(days=offset + weekday)).isoformat()
    return "待定"


def merge(meetings: list[MeetingMinutes], week_start: str | None = None, owner: str | None = None) -> Merged:
    if not meetings:
        raise NotesError("EMPTY_INPUT", "至少需要一场会议。", "传入 prepare_meeting_notes 返回的 minutes 对象列表。")
    start = end = None
    if week_start:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", week_start) or iso_date(week_start) != week_start:
            raise NotesError("INVALID_DATE", "week_start 必须为有效的 YYYY-MM-DD。", "传入目标周的周一日期。")
        start = date.fromisoformat(week_start)
        if start.weekday() != 0:
            raise NotesError("INVALID_DATE", "week_start 必须是周一。", "传入目标周的周一日期。")
        end = start + timedelta(days=6)
    items, seen, warnings = [], set(), []
    for index, meeting in enumerate(meetings, 1):
        fingerprint = json.dumps(meeting.model_dump(), sort_keys=True, ensure_ascii=False)
        if fingerprint in seen:
            warnings.append(f"第 {index} 份输入与前文完全相同，未重复计入。")
            continue
        seen.add(fingerprint)
        for action in meeting.actions:
            if owner and action.owner != owner:
                continue
            due_date = resolve_due(action.due_text, meeting.meeting_date)
            if start and due_date != "待定" and not (start.isoformat() <= due_date <= end.isoformat()):
                continue
            items.append(MergedAction(**action.model_dump(), meeting_title=meeting.title,
                                      meeting_date=meeting.meeting_date, meeting_index=index, due_date=due_date))
    items.sort(key=lambda a: (a.owner == "待定", a.owner, a.due_date == "待定", a.due_date, a.meeting_index, a.source_ref))
    by_owner = [ActionGroup(key=name, items=[a for a in items if a.owner == name]) for name in dict.fromkeys(a.owner for a in items)]
    dates = sorted({a.due_date for a in items}, key=lambda d: (d == "待定", d))
    by_date = [ActionGroup(key=day, items=[a for a in items if a.due_date == day]) for day in dates]
    if any(a.due_date == "待定" for a in items):
        warnings.append("无法确定日期的待办单列“待定”，周筛选仍保留；未使用系统当前日期补全。")
    lines = ["# 周行动表", "", f"范围：{week_start} 至 {end.isoformat()}" if start else "范围：本次传入的全部会议", ""]
    for heading, groups in [("按负责人", by_owner), ("按日期", by_date)]:
        lines += [f"## {heading}", ""]
        for group in groups:
            lines += [f"### {cell(group.key)}", "", "| 负责人 | 事项 | 日期 | 期限原话 | 状态 | 来源会议 | 原文依据 |", "|---|---|---|---|---|---|---|"]
            lines += [f"| {cell(a.owner)} | {cell(a.text)} | {a.due_date} | {cell(a.due_text)} | {a.status} | {cell(a.meeting_title)} / {cell(a.meeting_date)} / 输入{a.meeting_index} | {a.source_ref}：{cell(a.source_text)} |" for a in group.items]
            lines += [""]
        if not groups:
            lines += ["无符合条件的待办。", ""]
    return Merged(week_start=week_start, week_end=end.isoformat() if end else None, items=items,
                  by_owner=by_owner, by_date=by_date, markdown="\n".join(lines), warnings=warnings)

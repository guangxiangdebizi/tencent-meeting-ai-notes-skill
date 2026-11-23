import re
from datetime import date

from markdown_it import MarkdownIt

from .models import Action, Evidence, MAX_BYTES, MeetingMinutes, Prepared
from .render import render_minutes


class NotesError(ValueError):
    def __init__(self, code: str, message: str, next_action: str):
        self.code = code
        self.message = message
        self.next_action = next_action
        super().__init__(message)


ALIASES = {
    "topics": {"会议概览", "概览", "会议概要", "会议摘要", "摘要", "讨论要点", "讨论内容", "会议小结", "议题小结", "小结", "议题", "会议内容", "总结", "summary", "overview", "discussion", "topics"},
    "decisions": {"决策", "会议决策", "决议", "会议决议", "已确定事项", "决定", "decisions", "decision"},
    "actions": {"待办", "待办事项", "行动项", "行动计划", "后续行动", "后续安排", "任务分工", "todos", "todo", "action items", "actions"},
    "unresolved": {"未决问题", "待确认", "待确认事项", "待解决问题", "遗留问题", "开放问题", "open questions", "unresolved", "questions"},
}
META = {
    "title": {"会议主题", "会议标题", "主题", "title"},
    "meeting_date": {"会议日期", "会议时间", "会议开始", "日期", "时间", "date"},
    "participants": {"参会人", "参会人员", "与会人员", "参会者", "参与人", "participants", "attendees"},
}
PRIVATE_META = re.compile(r"^(?:meeting_id|room|room_id|会议号|房间号|来源|实时纪要\s*\d+\s*条).*[:：]", re.I)
DATE_PATTERN = r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?"
DUE_PATTERN = rf"(?:{DATE_PATTERN}|(?:下下|下|本|这)?(?:周|星期)[一二三四五六日天]|今天|明天|后天|本周末|下周末|月底|下月底|\d{{1,2}}月\d{{1,2}}[日号])(?:\s*\d{{1,2}}[:：]\d{{2}})?(?:之前|以前|前|内|截止)?"


def plain(value: str) -> str:
    tokens = MarkdownIt("commonmark", {"html": False}).parseInline(value)
    children = tokens[0].children if tokens else []
    return "".join(t.content if t.type not in {"softbreak", "hardbreak"} else "\n"
                   for t in children or [] if t.nesting == 0).strip()


def key(value: str) -> str:
    return re.sub(r"^(?:\d+[.、)）]\s*|[一二三四五六七八九十]+[、.、]\s*)", "", plain(value)).strip(" :：").lower()


def section_kind(value: str) -> str | None:
    label = key(value)
    return next((kind for kind, aliases in ALIASES.items() if label in aliases), None)


def iso_date(value: str) -> str | None:
    match = re.search(DATE_PATTERN, value)
    if match:
        parts = re.findall(r"\d+", match.group())
        try:
            return date(*map(int, parts)).isoformat()
        except ValueError:
            return None
    return None


def check_size(value: str) -> None:
    if len(value.encode("utf-8")) > MAX_BYTES:
        raise NotesError("INPUT_TOO_LARGE", "输入超过 256 KiB。", "拆分为单场会议或缩短原文。")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", value):
        raise NotesError("INVALID_TEXT", "输入含 Office 文件不支持的控制字符。", "移除控制字符后重试。")


def parse_action(item: Evidence) -> Action:
    text = item.text.strip()
    checked = re.match(r"^\[([ xX])\]\s*", text)
    status = "已完成" if checked and checked[1].lower() == "x" else "待办"
    text = re.sub(r"^\[[ xX]\]\s*", "", text)
    owner, due = "待定", "待定"
    owner_match = re.search(r"(?:负责人|责任人|owner)\s*[:：]\s*([^\n|;；，,]+)", text, re.I)
    if owner_match:
        owner = owner_match[1].strip()
        text = text[:owner_match.start()] + text[owner_match.end():]
    else:
        prefix = re.match(r"^([\w\u4e00-\u9fff·、 /-]{1,20})[:：]\s*", text)
        if prefix and key(prefix[1]) not in {"任务", "事项", "内容", "说明", "目标", "备注", "期限", "截止", "截止日期", "状态"}:
            owner = prefix[1].strip()
            text = text[prefix.end():]
    due_match = re.search(r"(?:截止日期|截止时间|截止|期限|due)\s*[:：]\s*([^\n|;；]+)", text, re.I)
    if due_match:
        due = due_match[1].strip()
        text = text[:due_match.start()] + text[due_match.end():]
    else:
        due_match = re.search(DUE_PATTERN, text)
        if due_match and (not text[:due_match.start()].strip() or
                          re.search(r"(?:之前|以前|前|内|截止)$", due_match[0])):
            due = due_match[0].strip()
            # Only remove an introductory deadline; dates inside the task may be its subject.
            if not text[:due_match.start()].strip():
                text = text[due_match.end():].lstrip(" ，,:：前")
    status_match = re.search(r"状态\s*[:：]\s*(已完成|进行中|待办|待定)", text)
    if status_match:
        status = status_match[1]
        text = text[:status_match.start()] + text[status_match.end():]
    text = text.strip(" \n|;；，,") or item.text
    return Action(**{**item.model_dump(), "text": text}, owner=owner, due_text=due, status=status)


def prepare(text: str, title: str | None = None, meeting_date: str | None = None) -> Prepared:
    check_size(text)
    if not text.strip():
        raise NotesError("EMPTY_INPUT", "会议原文为空。", "粘贴元宝笔记、腾讯会议文本或 Markdown。")
    if meeting_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", meeting_date):
        raise NotesError("INVALID_DATE", "meeting_date 必须为 YYYY-MM-DD。", "使用明确的会议日期，或不传此参数。")
    if meeting_date and iso_date(meeting_date) != meeting_date:
        raise NotesError("INVALID_DATE", "会议日期不存在。", "核对年月日后重试。")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    tokens = MarkdownIt("commonmark", {"html": False}).enable("table").parse("\n".join(lines))
    minutes = MeetingMinutes()
    headings: list[tuple[int, str, str | None]] = []
    warnings = []

    def metadata(value: str) -> bool:
        clean = plain(re.sub(r"^[-*+]\s+", "", value))
        if PRIVATE_META.match(clean):
            return True
        match = re.match(r"^([^:：\n]+)[:：]\s*(.+)$", clean)
        if not match:
            return False
        field = next((name for name, names in META.items() if key(match[1]) in names), None)
        if field == "title":
            minutes.title = match[2]
        elif field == "meeting_date":
            minutes.meeting_date = iso_date(match[2]) or match[2]
        elif field == "participants":
            minutes.participants.extend(n.strip() for n in re.split(r"[、,，;；/]|\s+和\s+", match[2]) if n.strip())
        return field is not None

    def add(value: str, start: int, end: int, forced: str | None = None) -> None:
        value = plain(value)
        if not value or metadata(value):
            return
        kind = forced or (headings[-1][2] if headings else None) or "other_notes"
        item = Evidence(text=value, source_ref=f"L{start + 1}-L{end}",
                        source_text="\n".join(lines[start:end]).strip(),
                        section=" / ".join(h[1] for h in headings))
        if kind == "actions":
            minutes.actions.append(parse_action(item))
        else:
            getattr(minutes, kind).append(item)

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "table_open":
            end_i = i + 1
            while tokens[end_i].type != "table_close":
                end_i += 1
            rows = []
            j = i + 1
            while j < end_i:
                if tokens[j].type == "tr_open":
                    row_start, values = tokens[j], []
                    j += 1
                    while tokens[j].type != "tr_close":
                        if tokens[j].type == "inline":
                            values.append(plain(tokens[j].content))
                        j += 1
                    rows.append((row_start, values))
                j += 1
            headers = [key(h) for h in rows[0][1]] if rows else []
            task_col = next((n for n, h in enumerate(headers) if h in {"事项", "任务", "待办", "行动项", "task", "action"}), None)
            if headings and headings[-1][2] == "actions" and task_col is not None:
                for row, values in rows[1:]:
                    if not values[task_col]:
                        continue
                    fields = []
                    for aliases, label in [({"负责人", "责任人", "owner"}, "负责人"), ({"期限", "截止日期", "截止时间", "due"}, "期限"), ({"状态", "status"}, "状态")]:
                        col = next((n for n, h in enumerate(headers) if h in aliases), None)
                        if col is not None and values[col]:
                            fields.append(f"{label}：{values[col]}")
                    add("；".join([values[task_col], *fields]), *row.map)
            else:
                add("\n".join(" | ".join(v) for _, v in rows), *token.map, "other_notes")
            i = end_i + 1
            continue
        if token.type == "heading_open":
            label = tokens[i + 1].content
            level = int(token.tag[1:])
            while headings and headings[-1][0] >= level:
                headings.pop()
            kind = section_kind(label)
            if kind is None and headings:
                kind = headings[-1][2]
            headings.append((level, plain(label), kind))
            if level == 1 and minutes.title == "未命名会议" and not section_kind(label):
                minutes.title = plain(label)
            i += 3
            continue
        if token.type == "list_item_open":
            end_i, depth = i + 1, 1
            while depth:
                if tokens[end_i].type == "list_item_open":
                    depth += 1
                elif tokens[end_i].type == "list_item_close":
                    depth -= 1
                end_i += 1
            inline = [t.content for t in tokens[i + 1:end_i] if t.type == "inline"]
            value = "\n".join(inline)
            # A list item may introduce an explicitly labelled section.
            label = re.match(r"^([^:：\n]+)[:：]\s*(.*)$", plain(inline[0]) if inline else "")
            if label and section_kind(label[1]):
                forced = section_kind(label[1])
                children = inline[1:] if not label[2] else [label[2], *inline[1:]]
                for child in children:
                    add(child, token.map[0], token.map[1], forced)
            else:
                # Separate nested tasks, but keep owner/deadline subfields with their parent.
                nested_tasks = [t for t in tokens[i + 1:end_i] if t.type == "list_item_open"]
                fields = all(re.match(r"^(负责人|责任人|期限|截止日期|截止时间|截止|状态|owner|due)[:：]", plain(v), re.I) for v in inline[1:])
                if nested_tasks and not fields:
                    add(inline[0], token.map[0], min(token.map[1], nested_tasks[0].map[0]))
                    i += 1
                    while i < end_i and tokens[i].type != "list_item_open":
                        i += 1
                    continue
                add(value, token.map[0], token.map[1])
            i = end_i
            continue
        if token.type == "paragraph_open":
            value = tokens[i + 1].content
            kind = section_kind(value)
            label = re.match(r"^([^:：\n]+)[:：]\s*(.+)$", plain(value), re.S)
            if kind:
                headings = [(2, plain(value).strip(" :："), kind)]
            elif label and section_kind(label[1]):
                headings = [(2, plain(label[1]), section_kind(label[1]))]
                add(label[2], *token.map)
            else:
                # Plain-text exports often put several metadata/labelled lines in one paragraph.
                if "\n" in value and any(re.match(r"^(会议|参会|与会|待办|决策|未决)", plain(v)) for v in value.splitlines()):
                    for offset, line in enumerate(value.splitlines()):
                        label = re.match(r"^([^:：]+)[:：]\s*(.*)$", plain(line))
                        if section_kind(line):
                            headings = [(2, plain(line).strip(" :："), section_kind(line))]
                        elif label and section_kind(label[1]):
                            headings = [(2, plain(label[1]), section_kind(label[1]))]
                            if label[2]:
                                add(label[2], token.map[0] + offset, token.map[0] + offset + 1)
                        else:
                            add(line, token.map[0] + offset, token.map[0] + offset + 1)
                else:
                    add(value, *token.map)
            i += 3
            continue
        if token.type in {"fence", "code_block", "html_block"}:
            add(token.content, *token.map, "other_notes")
        i += 1
    if title:
        minutes.title = title
    if meeting_date:
        minutes.meeting_date = meeting_date
    minutes.participants = list(dict.fromkeys(minutes.participants))
    # Revalidate values assigned during parsing before rendering or exporting.
    minutes = MeetingMinutes.model_validate(minutes.model_dump())
    if minutes.other_notes:
        warnings.append("未分类内容保留在“其他记录”；散文中的隐含决策和承诺未自动推断。")
    if any(a.owner == "待定" or a.due_text == "待定" for a in minutes.actions):
        warnings.append("未注明的负责人或期限标为“待定”；相对期限保留原话。")
    return Prepared(minutes=minutes, markdown=render_minutes(minutes), warnings=warnings)

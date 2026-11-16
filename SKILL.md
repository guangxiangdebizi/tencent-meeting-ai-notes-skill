---
name: tencent-meeting-ai-notes
description: Export Tencent Meeting (腾讯会议) Yuanbao AI notes — post-meeting summaries with to-dos and real-time note fragments — from the Windows desktop client into one Markdown file per meeting. Use when an agent needs to read what was said or decided in a Tencent Meeting, list recent meetings that have AI notes, collect new meeting to-dos for a daily digest, or recover a summary that only exists in the 元宝笔记 web view. Read-only; never publish real meeting content.
---

# Tencent Meeting AI Notes

The local Tencent Meeting database is encrypted, but a running `wemeetapp` client keeps the Yuanbao note JSON of every meeting it has loaded in recent months in process memory. `scripts/wemeet_notes.py` scans that memory, groups fragments by meeting, and writes Markdown. No page opening or scrolling is needed.

## Operating Rules

1. The scripts are read-only. Never modify notes or client data.
2. Never publish or commit real notes, dumps, meeting IDs, room IDs, user IDs or the `output/` directory.
3. Run the memory scan with the same privilege level as `wemeetapp` (usually administrator).
4. Only use `--ui-grab` when the memory scan has no summary for a meeting the user expects. It moves the mouse on the user's desktop; the script checks the user is away first and gives up with `owner_active` otherwise. Do not override that check.

## Workflow

### 1. Scan and list

On the Windows machine running Tencent Meeting:

```powershell
python scripts\wemeet_notes.py --list
```

Each line is `start time, meeting_id, subject, counts (实时N 总结M), path`. Files go to `.\output\` (`--out` to change):

- `YYYY-MM-DD_<meeting_id>.md`: from memory. Contains 会后总结（完整版）, 会后总结（简版） and 实时纪要 with in-meeting and Beijing timestamps.
- `YYYY-MM-DD_ui_<code>.md`: from the UI fallback.
- `raw/dump.jsonl.gz`: raw scan.

An existing meeting file is kept when it is longer than the new result, because a restarted client may only hold part of a meeting.

### 2. Read a meeting

```powershell
python scripts\wemeet_notes.py                    # latest meeting
python scripts\wemeet_notes.py --meeting <id>     # a specific one
```

For a daily digest, `--digest-since <unix_ts>` prints only meetings with notes newer than that time, plus their 待办 items.

Add `--no-refresh` to reuse the last dump. To parse on another machine, copy `raw/dump.jsonl.gz` and run `python3 scripts/wemeet_notes.py --dump dump.jsonl.gz --list`.

### 3. UI fallback for missing summaries

Newer clients sometimes keep the post-meeting summary only in the 元宝笔记 web view, so memory has `总结0`. Then:

- On the user's desktop in an elevated terminal: `--ui-grab direct`.
- Over SSH or from an agent session: `--ui-grab task`. This registers an elevated, interactive scheduled task `wemeet-ui-grab` that runs `wemeet_ui_grab.py` on the logged-in desktop and waits for its result.

The grab uses an open 元宝笔记 window, or clicks 立即查看 on a 图文总结已生成 toast after confirming its text. It then chooses 复制为Markdown and reads the clipboard. Afterwards it restores the clipboard and foreground window and closes any window it opened. It needs `pip install pyautogui pyperclip pywin32`.

Click coordinates in `wemeet_ui_grab.py` are physical pixels calibrated on the author's machine. If `copy_failed` comes back, take a screenshot of the 元宝笔记 window and re-measure `COPY_ARROW` / `COPY_MD`.

## When Notes Are Missing

- `腾讯会议没在运行`: start the client. A freshly started client only has meetings it has loaded since, so ask the user to open that meeting's 元宝纪要 once.
- Meeting listed with `总结0`: the meeting may still be running, or the summary is web-only (use the UI fallback).
- `owner_active`: someone is using the computer. Retry later.
- Scan finds nothing although the client is running: the scan is probably not elevated.

## Privacy Checklist

Before sharing anything, remove `output/`, dumps, meeting IDs, room IDs, user IDs and company-sensitive content. Use `examples/sanitized-output.md` for examples.

---
name: tencent-meeting-ai-notes
description: Extract and package Tencent Meeting Yuanbao real-time AI notes from the Windows desktop client. Use when Codex needs to export Tencent Meeting history metadata, open or scroll Yuanbao notes, recover lazily loaded real-time note fragments from wemeetapp renderer memory, diagnose incomplete note extraction such as partial x/y counts, or produce clean Markdown meeting-minute artifacts without publishing private meeting content.
---

# Tencent Meeting AI Notes

Use this skill for Windows Tencent Meeting workflows where Yuanbao AI notes are visible in the desktop client but are incomplete through UI automation.

## Operating Rules

1. Treat the local Tencent Meeting client as the source of truth.
2. Never publish or commit real meeting notes, meeting IDs, room IDs, user IDs, tokens, client databases, or exported output directories.
3. Prefer a two-stage extraction: load the Yuanbao page in the UI, then scan `wemeetapp` renderer memory.
4. Do not trust a hard-coded expected note count unless it came from the current page or API response.
5. If extraction returns fewer notes than expected, reopen the Yuanbao note page, scroll it fully, wait a few seconds, and run extraction again.

## Workflow

### 1. Open the target meeting

Optionally export meeting-history metadata first:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export_tencent_meeting_history.ps1 `
  -DatabasePath "<path-to-wemeet-profile-db>" `
  -SqliteExe "<path-to-sqlite3.exe>" `
  -OutputRoot ".\output"
```

In Tencent Meeting for Windows:

1. Open the meeting history list.
2. Search for the target meeting.
3. Open its detail page.
4. Open the Yuanbao notes page for that meeting.

Keep the Yuanbao notes page open while extracting. The data must be loaded into the embedded Chromium renderer process before memory extraction can find it.

### 2. Trigger lazy loading

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scroll_yuanbao_notes.ps1
```

This focuses the Yuanbao notes window and sends repeated Page Down events. If the window is not found, ask the user to open the notes page manually and rerun the script.

### 3. Extract real-time notes

Run the extractor with explicit meeting identifiers:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\extract_yuanbao_realtime_notes.ps1 `
  -MeetingId "<meeting_id>" `
  -RoomId "<room_id>" `
  -MeetingStartTs "<unix_seconds>" `
  -MeetingTitle "<title>" `
  -MeetingTimeRange "<yyyy-mm-dd hh:mm - hh:mm>" `
  -Participants "<names>" `
  -OutputFile ".\output\meeting_realtime_notes.md"
```

Set `-ExpectedNoteCount` only when the count is verified from the current page or API response. Leave it unset when unsure.

### 4. Validate completeness

Check the generated Markdown header:

- `纪要条数` should reflect the actual extracted count.
- `提取状态` should say whether the run reached a verified expected count.
- The first and last timestamps should match the real meeting range.

If the output starts in the middle of the meeting or ends early, repeat the lazy-load step and rerun extraction. Tencent Meeting may evict or reload renderer memory.

## Why Extraction Can Be Incomplete

Incomplete Yuanbao note exports usually come from one of these causes:

1. The notes page was not open, so the renderer never loaded the API response.
2. The page was open but not scrolled enough, so later fragments were never lazily loaded.
3. A script scanned only one `wemeetapp` PID, while the data lived in another renderer process.
4. A script closed a process handle before later scan passes used it.
5. A stale hard-coded count such as `15/29` or `x/29` was treated as authoritative.

The bundled extractor avoids these failure modes by scanning all `wemeetapp` processes, reopening handles per pass, scanning multiple cache patterns, and reporting actual extracted counts.

## Privacy Checklist

Before publishing, sharing, or committing outputs:

- Remove `output/`, `腾讯会议整理输出/`, raw `.db` files, and any generated meeting minutes.
- Remove concrete meeting IDs, room IDs, user IDs, account IDs, tokens, and company-sensitive content.
- Use `examples/sanitized-output.md` style examples only.

# Tencent Meeting AI Notes Skill

Codex skill and Windows PowerShell tools for extracting Tencent Meeting Yuanbao real-time AI notes when the desktop client loads notes lazily and normal UI automation only captures part of the meeting.

**Topics:** `codex-skill`, `tencent-meeting`, `yuanbao`, `meeting-notes`, `powershell`, `windows`, `cef`, `memory-extraction`, `ai-notes`

## What It Does

- Scrolls the Tencent Meeting Yuanbao notes page to trigger lazy loading.
- Scans all local `wemeetapp` processes instead of relying on a single PID.
- Extracts `note_info` fragments from renderer memory and formats them as Markdown.
- Avoids stale hard-coded totals such as `15/29` by reporting the actual extracted count unless a verified expected count is provided.
- Documents the failure modes that commonly cause incomplete real-time meeting notes.

## Repository Layout

```text
.
├── SKILL.md
├── scripts/
│   ├── extract_yuanbao_realtime_notes.ps1
│   ├── export_tencent_meeting_history.ps1
│   └── scroll_yuanbao_notes.ps1
├── examples/
│   └── sanitized-output.md
├── README.md
├── LICENSE
└── .gitignore
```

## Requirements

- Windows
- Tencent Meeting desktop client
- PowerShell 5.1 or newer
- A Yuanbao notes page already opened in Tencent Meeting

The extractor reads memory from local `wemeetapp` processes. Some environments may require running PowerShell with sufficient permissions to read those processes.

## Quick Start

Optionally export local meeting-history metadata from a Tencent Meeting SQLite database:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export_tencent_meeting_history.ps1 `
  -DatabasePath "C:\path\to\WeMeet\Global\Database\your-profile.db" `
  -SqliteExe "C:\path\to\sqlite3.exe" `
  -OutputRoot ".\output"
```

Open the target meeting in Tencent Meeting, then open its Yuanbao notes page. Keep that page open.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scroll_yuanbao_notes.ps1
```

Then extract with explicit identifiers:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\extract_yuanbao_realtime_notes.ps1 `
  -MeetingId "1234567890123456789" `
  -RoomId "123456789" `
  -MeetingStartTs "1770000000" `
  -MeetingTitle "Example Meeting" `
  -MeetingTimeRange "2026-05-21 20:00 - 21:54" `
  -Participants "Alice, Bob" `
  -OutputFile ".\output\example_realtime_notes.md"
```

Only pass `-ExpectedNoteCount` if that number comes from the current page or current API response:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\extract_yuanbao_realtime_notes.ps1 `
  -MeetingId "1234567890123456789" `
  -RoomId "123456789" `
  -MeetingStartTs "1770000000" `
  -ExpectedNoteCount 64
```

## Why Tencent Meeting Notes Go Missing

Yuanbao notes are loaded through an embedded Chromium view and cached in renderer memory. The full content may not exist in memory until the page is opened and scrolled. Incomplete exports often happen because a script scans the wrong process, scans before lazy loading finishes, closes a process handle too early, or trusts an old expected count.

This project bakes those lessons into the workflow: scroll first, scan every `wemeetapp` process, run multiple extraction passes, and write honest completeness metadata into the Markdown header.

## Privacy

Do not commit real exported meeting notes. This repository intentionally ignores `output/`, Tencent Meeting export folders, local database files, and token-like artifacts. The included example is synthetic and sanitized.

## License

MIT

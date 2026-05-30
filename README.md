# 腾讯会议元宝实时纪要提取 Skill

这是一个给 Codex 使用的 skill，同时附带 Windows PowerShell 脚本，用来从腾讯会议桌面客户端中提取“元宝纪要”的实时 AI 纪要。它主要解决一个实际问题：腾讯会议的元宝纪要是懒加载的，普通 UI 自动化经常只能拿到一部分内容，例如只导出 `15/29` 这类不完整结果。

**标签：** `codex-skill`, `tencent-meeting`, `yuanbao`, `meeting-notes`, `powershell`, `windows`, `cef`, `memory-extraction`, `ai-notes`

## 功能说明

- 自动滚动腾讯会议元宝纪要页面，触发懒加载。
- 扫描所有本地 `wemeetapp` 进程，不依赖单个固定 PID。
- 从渲染进程内存中提取 `note_info` 片段，并整理成 Markdown。
- 不再盲信 `15/29` 这类历史硬编码总数；除非传入已验证总数，否则只报告本次真实提取条数。
- 记录实时纪要抽不全的常见原因，方便后续排查和复用。

## 仓库结构

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

## 运行要求

- Windows
- 腾讯会议桌面客户端
- PowerShell 5.1 或更新版本
- 已经在腾讯会议中打开目标会议的“元宝纪要”页面

提取脚本会读取本地 `wemeetapp` 进程内存。某些环境下需要用有足够权限的 PowerShell 运行。

## 快速开始

可以先从腾讯会议本地 SQLite 数据库导出会议历史元数据：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export_tencent_meeting_history.ps1 `
  -DatabasePath "C:\path\to\WeMeet\Global\Database\your-profile.db" `
  -SqliteExe "C:\path\to\sqlite3.exe" `
  -OutputRoot ".\output"
```

然后在腾讯会议里打开目标会议详情页，并进入该会议的“元宝纪要”页面。保持这个页面打开。

先滚动加载：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scroll_yuanbao_notes.ps1
```

再用明确的会议标识提取实时纪要：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\extract_yuanbao_realtime_notes.ps1 `
  -MeetingId "1234567890123456789" `
  -RoomId "123456789" `
  -MeetingStartTs "1770000000" `
  -MeetingTitle "示例会议" `
  -MeetingTimeRange "2026-05-21 20:00 - 21:54" `
  -Participants "张三, 李四" `
  -OutputFile ".\output\example_realtime_notes.md"
```

只有当总条数来自当前页面或当前 API 响应时，才传入 `-ExpectedNoteCount`：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\extract_yuanbao_realtime_notes.ps1 `
  -MeetingId "1234567890123456789" `
  -RoomId "123456789" `
  -MeetingStartTs "1770000000" `
  -ExpectedNoteCount 64
```

## 为什么会抽不全

元宝纪要通过腾讯会议内嵌 Chromium 页面加载，内容会缓存到渲染进程内存中。完整内容不一定在页面打开时一次性进入内存，往往需要滚动页面后才会继续加载。

常见漏提原因包括：

- 页面没有真正打开到“元宝纪要”，只是停留在会议详情摘要页。
- 页面打开了但没有滚到底，后面的片段没有进入内存。
- 脚本只扫描了一个 `wemeetapp` PID，而真实数据在另一个渲染进程里。
- 脚本提前关闭进程句柄，导致后续补扫逻辑失效。
- 把旧的硬编码总数当成权威结果，例如误信 `15/29`。

这个仓库把这些教训固化到流程里：先滚动，再扫描所有 `wemeetapp` 进程，执行多轮提取，并在 Markdown 头部写入诚实的提取状态。

## 隐私说明

不要提交真实导出的会议纪要。本仓库已经通过 `.gitignore` 排除了 `output/`、腾讯会议导出目录、本地数据库文件和常见纪要输出文件。仓库里的示例是合成的脱敏内容，不包含真实会议内容、会议号、用户 ID 或 token。

## 许可证

MIT

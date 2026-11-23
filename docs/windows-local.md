# 本机模式（Windows）

这是一个给 Codex / Claude Code 等 agent 使用的 skill，附带 Windows 脚本，用来从腾讯会议桌面客户端导出“元宝纪要”：会后 AI 总结（含待办）和实时纪要片段，每场会议整理成一个 Markdown。

**标签：** `codex-skill`, `claude-skill`, `tencent-meeting`, `yuanbao`, `meeting-notes`, `windows`, `memory-extraction`, `ai-notes`

## 和旧版的区别

旧版（v1）要先打开元宝纪要页面、自动滚动触发懒加载，再按会议号逐场提取，经常只抽到一部分。现在的做法：

- **读取已加载的缓存。** 客户端内存中可能保留已打开会议的纪要片段。扫描结果受客户端版本和加载状态影响，不代表账号中的全部会议。
- **自动识别会议。** 从纪要的 `task_id` 里解析 meeting_id、房间号、开始时间、片段时间，会议主题从内存里的会议 URL 取，不用手动传参数。
- **同时拿到会后总结和实时纪要。** `note_type=2` 是会后总结（完整版 + 简版，含“待办”小节），`note_type=1` 是实时纪要片段。`@@(uid)@@` 会替换成参会人昵称。
- **界面兜底。** 新版客户端有时只把会后总结放在“元宝笔记”网页里，内存里找不到。`--ui-grab` 会打开“元宝笔记”窗口（或点“图文总结已生成”弹窗），用“复制为Markdown”取全文。动鼠标之前先确认没人在用电脑。
- **适合日报类定时任务。** `--digest-since` 只列出某个时间之后有新纪要的会议和待办。
- 已有的会议文件比新结果更完整时不覆盖（客户端重启后内存里可能只剩一部分）。

## 仓库结构

```text
.
├── SKILL.md
├── scripts/
│   ├── wemeet_notes.py       # 入口：扫描、解析、合并、输出
│   ├── wemeet_dump.ps1       # 扫描 wemeetapp 进程内存，导出 note_info（gzip）
│   └── wemeet_ui_grab.py     # 界面兜底：元宝笔记窗口「复制为Markdown」
├── examples/
│   └── sanitized-output.md
├── README.md
├── LICENSE
└── .gitignore
```

## 运行要求

- Windows，腾讯会议桌面客户端正在运行
- Python 3.9+（主流程只用标准库）
- PowerShell 5.1 或更新版本
- 只有用 `--ui-grab` 时才需要：`pip install pyautogui pyperclip pywin32`，并且有人登录着桌面

## 快速开始

```powershell
python scripts\wemeet_notes.py            # 扫描并打印最新一场会议的纪要
python scripts\wemeet_notes.py --list     # 列出所有找得到纪要的会议
python scripts\wemeet_notes.py --meeting <meeting_id>
python scripts\wemeet_notes.py --digest-since 1770000000   # 某时间之后的新纪要 + 待办
```

结果写到 `.\output\`：

- `YYYY-MM-DD_<meeting_id>.md`：内存扫描得到的会议
- `YYYY-MM-DD_ui_<会议号>.md`：界面抓取得到的会后总结
- `raw/dump.jsonl.gz`：原始扫描结果

扫描大约需要几十秒。客户端以管理员权限运行时，扫描进程也要用管理员权限。

### 远程 / agent 调用

在 Windows 上扫描，把 `output\raw\dump.jsonl.gz` 拷到任意机器解析：

```bash
python3 scripts/wemeet_notes.py --dump dump.jsonl.gz --out ./output --list
```

通过 SSH 调用时点不到桌面窗口，界面兜底要用计划任务方式：

```powershell
python scripts\wemeet_notes.py --ui-grab task
```

它会注册一个提权、交互式登录的计划任务 `wemeet-ui-grab`，在用户桌面里运行 `wemeet_ui_grab.py`，然后等结果。直接在桌面上的管理员终端里运行时用 `--ui-grab direct`。

## 界面抓取的注意事项

- 系统空闲不到 `--ui-idle` 秒（默认 300）时，先挂低级键鼠钩子观察 20 秒；有真人输入就放弃，返回 `owner_active`，下次再试。
- 点击坐标是物理像素，按作者的电脑校准（`NOTE_RECT`、`COPY_ARROW`、`COPY_MD`、`TOAST_BTN`，在 `wemeet_ui_grab.py` 开头）。界面布局或显示缩放不同时需要重新量。
- 弹窗按 Qt 窗口类名 `Qt680QWindowToolSaveBits` 查找，客户端升级 Qt 后可能要改。
- 走不通的路：Ctrl+A 复制被网页拦截；网页文字没有暴露给 UI Automation；对主窗口做 UIA 全树遍历会卡死。

## 拿不到纪要的常见原因

- 腾讯会议没在运行，或刚重启过，还没加载过那场会议：在客户端里打开一次那场会议的元宝纪要。
- 会议还没结束，只有实时纪要，没有会后总结。
- 新版客户端的会后总结只在元宝笔记网页里：用 `--ui-grab`。
- 扫描进程权限比 `wemeetapp` 低，读不到内存。

## 隐私说明

脚本只读，不修改纪要和客户端数据。不要提交真实导出的会议纪要：`.gitignore` 已经排除 `output/`、dump 和常见纪要文件名。仓库里的示例是合成的脱敏内容。

## 许可证

MIT

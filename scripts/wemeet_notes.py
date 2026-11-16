#!/usr/bin/env python3
"""腾讯会议元宝纪要（AI 总结 + 实时纪要）导出，只读。

腾讯会议本地库是加密的，但客户端 wemeetapp 进程内存里缓存着历次会议的元宝纪要 JSON
（note_type=1 实时纪要片段，note_type=2 会后总结，含待办）。做法：
  1. wemeet_dump.ps1 扫描全部 wemeetapp 进程内存，导出 note_info 片段到 output/raw/dump.jsonl.gz；
  2. 本脚本解析、按 meeting_id 去重合并，每场会议一个 md：output/YYYY-MM-DD_<meeting_id>.md。
     已有文件比新结果内容多时不覆盖（客户端重启后内存里可能只剩部分）。
不用滚动页面：客户端开着时会把几个月内打开过的会议都留在内存里。腾讯会议没开着就拿不到。

新版客户端的会后总结有时只在元宝笔记网页里，内存扫描找不到。加 --ui-grab 时再跑 wemeet_ui_grab.py：
开着「元宝笔记」窗口、或有「图文总结已生成」弹窗时，点开并「复制为Markdown」，
存 output/YYYY-MM-DD_ui_<会议号>.md，并入 --list / --digest-since。
动鼠标前确认没人在用电脑（系统空闲 --ui-idle 秒，或观察 20 秒内没有真人键鼠），否则跳过。

用法（在 Windows 上）：
  wemeet_notes.py                 刷新并打印最新一场的完整纪要
  wemeet_notes.py --list          列出能找到纪要的会议
  wemeet_notes.py --meeting ID    打印指定会议
  wemeet_notes.py --digest-since UNIX_TS   列出该时间之后有新纪要的会议 + 待办（给日报类任务用）
  --no-refresh                    不重新扫内存，用上次的 dump
  --dump FILE                     解析别处拷来的 dump（任何系统都能跑，不扫内存）
  --ui-grab direct|task           界面抓取；direct 在当前进程里点（要在桌面上、管理员权限），
                                  task 通过提权的交互式计划任务点（适合 SSH / agent 远程调用）
"""
import argparse, base64, collections, datetime, gzip, hashlib, json, os, re, subprocess, sys, time, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
PS1 = HERE / "wemeet_dump.ps1"
UI_PY = HERE / "wemeet_ui_grab.py"
UI_TASK = "wemeet-ui-grab"
TZ = datetime.timezone(datetime.timedelta(hours=8))
OUTDIR = RAW = UI_INDEX = None

TID = re.compile(r'"task_id":\s*"(ainotes_task_[^"]*?_(\d+)_(\d+)_([12])_(\d{16,20})(?:_\d+)?)"')
UINFO = re.compile(r'"uid":\s*"(\d+)",\s*"nickname":\s*"([^"]{1,40})"')
START = re.compile(r'ainotes_task_ctt_uid:(\d{10})_')
URL = re.compile(r'meeting_id=(\d+)&av_room_id=(\d+)&meeting_subject=([^&\s]+)')


def refresh():
    """扫描本机 wemeetapp 内存，写 RAW。返回 None 或错误说明。"""
    if os.name != "nt":
        return "内存扫描只能在 Windows 上跑；别处请用 --dump 解析拷来的 dump"
    RAW.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1), "-Out", str(RAW)],
                       capture_output=True, timeout=600)
    out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    if "NO_WEMEET_PROCESS" in out:
        return "腾讯会议没在运行"
    if "DUMPED" not in out:
        return "内存扫描失败：" + out.strip()[-300:]
    return None


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ui_grab(mode, idle):
    """从元宝笔记窗口复制会后总结。返回 (结果 dict 或 None, 说明)。"""
    if os.name != "nt":
        return None, "界面抓取只能在 Windows 上跑"
    res_path = OUTDIR / "raw" / "ui_grab.json"
    done = Path(str(res_path) + ".done")
    res_path.parent.mkdir(parents=True, exist_ok=True)
    args = [str(UI_PY), "--idle", str(int(idle)), "--out", str(res_path)]
    if mode == "direct":
        if not is_admin():
            print("⚠️ 当前不是管理员权限；腾讯会议是管理员权限运行时点击会被忽略", file=sys.stderr)
        subprocess.run([sys.executable] + args, timeout=300)
    else:
        # 腾讯会议是管理员权限，点击要从提权的交互式计划任务里发；默认设置下用电池时任务会一直排队
        exe = Path(sys.executable).with_name("pythonw.exe")
        exe = exe if exe.exists() else Path(sys.executable)
        q = lambda s: "'" + s.replace("'", "''") + "'"
        argline = " ".join('"%s"' % a for a in args)
        ps = ("$a=New-ScheduledTaskAction -Execute {exe} -Argument {arg}; "
              "$p=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest; "
              "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
              "-ExecutionTimeLimit (New-TimeSpan -Minutes 5); "
              "Register-ScheduledTask -TaskName {t} -Action $a -Principal $p -Settings $s -Force | Out-Null; "
              "Start-ScheduledTask -TaskName {t}").format(exe=q(str(exe)), arg=q(argline), t=UI_TASK)
        done.unlink(missing_ok=True)
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, timeout=60)
        if r.returncode:
            return None, "创建计划任务失败：" + (r.stdout + r.stderr).decode("utf-8", "replace").strip()[-300:]
        for _ in range(150):
            if done.exists():
                break
            time.sleep(1)
        else:
            return None, "界面抓取超时（用户没登录桌面，或计划任务没启动）"
    if not res_path.exists():
        return None, "界面抓取没有输出"
    return json.loads(res_path.read_text(encoding="utf-8")), None


def ui_index():
    return json.loads(UI_INDEX.read_text(encoding="utf-8")) if UI_INDEX.exists() else {}


def store_ui(res):
    """把界面复制来的 Markdown 存成会议文件，更新 ui_index.json。返回 key。"""
    md = re.sub(r"\r*\n|\r", "\n", res["md"]).strip()
    toast = res.get("toast") or ""
    title = re.match(r"#\s*(.+)", md)[1].strip()
    code = re.search(r"会议号[:：]\s*(\d+)", toast)
    subj = re.search(r"主题[:：]\s*(.+)", toast)
    day = re.search(r"日期[:：]\s*(\d{4})年(\d{1,2})月(\d{1,2})日", toast)
    idx = ui_index()
    # 窗口本来就开着时拿不到弹窗里的会议号，按标题归到已有条目
    same = [k for k, e in idx.items() if e["title"] == title]
    key = code[1] if code else same[0] if same else "t" + hashlib.sha1(title.encode()).hexdigest()[:10]
    ent = idx.get(key, {"first_captured": res["captured_at"]})
    date = "%s-%02d-%02d" % (day[1], int(day[2]), int(day[3])) if day else ent.get("date") or fmt_ts(res["captured_at"])[:10]
    ent.update(title=title, code=code[1] if code else ent.get("code"), subject=subj[1].strip() if subj else ent.get("subject"),
               date=date, captured=res["captured_at"], path=str(OUTDIR / ("%s_ui_%s.md" % (date, key))))
    head = ["# %s - 元宝纪要" % (ent["subject"] or "腾讯会议"), "",
            "- 日期：%s　会议号：%s" % (date, ent["code"] or "?"),
            "- 来源：元宝笔记窗口「复制为Markdown」（wemeet_ui_grab.py，%s 抓取）" % fmt_ts(res["captured_at"]), "",
            "## 会后总结", ""]
    Path(ent["path"]).write_text("\n".join(head) + re.sub(r"^#\s*", "### ", md, count=1) + "\n", encoding="utf-8")
    idx[key] = ent
    UI_INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    return key


def unescape(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')


def quality(s):
    bad = len(re.findall(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]', s))
    return min(len(s), 4000) + 4 * len(re.findall(r'[\u4e00-\u9fff]', s)) - 300 * bad


def load(raw):
    meetings = collections.defaultdict(lambda: {"notes": {}, "summaries": {}, "room": None, "start": None, "subject": None})
    names = {}
    for line in gzip.open(raw, "rt", encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r["t"] == "url":
            m = URL.search(r["v"])
            if m:
                meetings[m[1]]["room"] = m[2]
                meetings[m[1]]["subject"] = urllib.parse.unquote(m[3])
            continue
        tail = r["tail"]
        for uid, nick in UINFO.findall(tail):
            names.setdefault(uid, nick)
        # 只要顶层纪要对象：字符串完整结束、后面紧跟 drill_info；note_insight_info 里的子条目跳过
        if not r.get("term") or not tail[1:].lstrip().startswith(', "drill_info"'):
            continue
        m = TID.search(tail[:1500])
        if not m:
            continue
        _, room, mid, typ, gen = m.groups()
        mt = meetings[mid]
        mt["room"] = mt["room"] or room
        sm = START.search(m[1])
        if sm:
            mt["start"] = int(sm[1])
        ts = re.search(r'"note_timestamp":\s*"([^"]*)"', tail[:1500])
        text = unescape(r["v"])
        bucket = mt["notes"] if typ == "1" else mt["summaries"]
        old = bucket.get(gen)
        if old is None or quality(text) > quality(old[1]):
            bucket[gen] = (ts[1] if ts else "", text)
    out = {}
    for mid, mt in meetings.items():
        gens = [int(g) for g in list(mt["notes"]) + list(mt["summaries"])]
        if not gens:
            continue
        mt["start"] = mt["start"] or min(gens) // 10**9
        mt["last"] = max(gens) // 10**9
        out[mid] = mt
    return out, names


def fmt_ts(sec):
    return datetime.datetime.fromtimestamp(sec, TZ).strftime("%Y-%m-%d %H:%M") if sec else "?"


def clean(text, names):
    text = re.sub(r'@@\((\d+)\)@@', lambda m: names.get(m[1], "某人"), text)
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]', '', text).strip()


def todos(text):
    """从总结里取「待办」小节的条目。"""
    items, on = [], False
    for ln in text.splitlines():
        if re.match(r'\s*#+\s', ln):
            on = "待办" in ln
            continue
        if on and ln.strip().startswith("-"):
            items.append(ln.strip()[1:].strip())
    return items


def render(mid, mt, names):
    sums = sorted(mt["summaries"].values(), key=lambda v: len(v[1]), reverse=True)
    out = ["# %s - 元宝纪要" % (mt["subject"] or "腾讯会议"), "",
           "- 会议开始：%s（最后一条纪要 %s）" % (fmt_ts(mt["start"]), fmt_ts(mt["last"])),
           "- meeting_id：%s　room：%s" % (mid, mt["room"]),
           "- 实时纪要 %d 条，会后总结 %d 份；来源：腾讯会议客户端内存（wemeet_notes.py）" % (len(mt["notes"]), len(sums)), ""]
    for i, (ts, text) in enumerate(sums):
        out += ["## %s" % ("会后总结（完整版）" if i == 0 else "会后总结（简版）"), "", clean(text, names), ""]
    if mt["notes"]:
        out += ["## 实时纪要（会议内时间 / 北京时间）", ""]
        for gen in sorted(mt["notes"], key=int):
            ts, text = mt["notes"][gen]
            out += ["### [%s] %s" % (ts, fmt_ts(int(gen) // 10**9)[11:]), "", clean(text, names), ""]
    return "\n".join(out)


def save_all(meetings, names):
    """每场会议写一个 md；已有文件更长时保留旧的。返回 {mid: path}。"""
    OUTDIR.mkdir(parents=True, exist_ok=True)
    paths = {}
    for mid, mt in meetings.items():
        p = OUTDIR / ("%s_%s.md" % (fmt_ts(mt["start"])[:10], mid))
        md = render(mid, mt, names)
        if not p.exists() or len(md) >= len(p.read_text(encoding="utf-8")):
            p.write_text(md, encoding="utf-8")
        paths[mid] = p
    return paths


def main():
    global OUTDIR, RAW, UI_INDEX
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--meeting")
    ap.add_argument("--digest-since", type=float)
    ap.add_argument("--no-refresh", action="store_true")
    ap.add_argument("--dump", help="解析这个 dump.jsonl.gz，不扫内存")
    ap.add_argument("--out", default="output", help="输出目录（默认 ./output）")
    ap.add_argument("--ui-grab", choices=["direct", "task"])
    ap.add_argument("--ui-idle", type=float, default=300, help="离开电脑多少秒后才允许界面抓取（默认 300）")
    a = ap.parse_args()
    if os.name == "nt":  # 中文 Windows 控制台默认 GBK，重定向时输出 emoji 会报错
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    OUTDIR = Path(a.out).resolve()
    RAW = Path(a.dump).resolve() if a.dump else OUTDIR / "raw" / "dump.jsonl.gz"
    UI_INDEX = OUTDIR / "ui_index.json"
    err = uierr = None
    if not (a.no_refresh or a.dump):
        err = refresh()
    if a.ui_grab:
        res, uierr = ui_grab(a.ui_grab, a.ui_idle)
        if res and res["status"] == "ok":
            store_ui(res)
        elif res and res["status"] == "owner_active":
            uierr = "有新的元宝纪要待抓取，但有人正在用电脑，稍后再试"
        elif res and res["status"] != "nothing":
            uierr = "界面抓取失败：%s %s" % (res["status"], res.get("error") or res.get("clip") or "")
    if err and not RAW.exists():
        sys.exit("❌ " + err)
    meetings, names = load(RAW) if RAW.exists() else ({}, {})
    paths = save_all(meetings, names)
    if err:
        print("⚠️ 本次没刷新（%s），用的是上次的 dump" % err)
    if uierr:
        print("⚠️ " + uierr)
    # 统一成 (排序时间, 显示时间, id, 主题, 条数说明, 路径, 总结正文)；界面抓取的按首次抓取时间排
    rows = []
    for mid, mt in meetings.items():
        sums = sorted(mt["summaries"].values(), key=lambda v: len(v[1]), reverse=True)
        rows.append((mt["start"], mt["last"], fmt_ts(mt["start"]), mid, mt["subject"] or "?",
                     "实时%d\t总结%d" % (len(mt["notes"]), len(sums)), paths[mid], clean(sums[0][1], names) if sums else ""))
    for key, e in ui_index().items():
        md = Path(e["path"]).read_text(encoding="utf-8") if Path(e["path"]).exists() else ""
        rows.append((e["first_captured"], e["first_captured"], e["date"], key, "%s · %s" % (e["subject"] or "?", e["title"]),
                     "界面\t总结1", e["path"], md))
    rows.sort(key=lambda r: r[0], reverse=True)
    if a.digest_since is not None:
        new = [r for r in rows if r[1] > a.digest_since]
        for _, _, when, mid, subj, cnt, path, summ in new:
            print("- %s「%s」：%s → `%s`" % (when, subj, cnt.replace("\t", "、"), path))
            for t in todos(summ):
                print("  - 待办：" + t)
            if not summ:
                print("  - 还没有会后总结（会议可能没结束，或客户端没加载总结页）")
        if not new:
            print("- 没有新的腾讯会议纪要")
        return
    if a.list:
        for _, _, when, mid, subj, cnt, path, _ in rows:
            print("%s\t%s\t%s\t%s\t%s" % (when, mid, subj, cnt, path))
        return
    if not rows:
        sys.exit("没有找到元宝纪要")
    row = next((r for r in rows if r[3] == a.meeting), None) if a.meeting else rows[0]
    if not row:
        sys.exit("没有这场会议：" + a.meeting)
    print(Path(row[6]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

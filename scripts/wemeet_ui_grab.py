# 内存扫描拿不到的会后总结，从腾讯会议界面复制出来（只读，不改纪要）：
#   1. 已经开着「元宝笔记」窗口就直接用；否则找「图文总结已生成」弹窗，确认文字后点「立即查看」；
#   2. 会议概览右上角复制下拉 →「复制为Markdown」，读剪贴板；
#   3. 恢复剪贴板、关掉自己打开的窗口、把前台还给原来的窗口。
# 腾讯会议默认以管理员权限运行，本脚本也要提权，并且在用户桌面里运行（SSH / 服务会话里点不到窗口）。
# 依赖：pip install pyautogui pyperclip pywin32
# 用法：wemeet_ui_grab.py [--idle 300] [--watch 20] [--out ui_grab.json]
# 结果写 --out 指定的 json，结束时再写同名 .done（给计划任务方式轮询用）。
import sys, os, time, json, ctypes, subprocess, traceback, argparse
ctypes.windll.user32.SetProcessDPIAware()
import pyautogui, pyperclip, win32gui, win32con

ap = argparse.ArgumentParser()
ap.add_argument('--idle', type=float, default=300, help='系统空闲超过这么多秒直接动手')
ap.add_argument('--watch', type=float, default=20, help='否则先观察这么多秒，没有真人键鼠才动手')
ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui_grab.json'))
ARGS = ap.parse_args()
OUT, DONE = ARGS.out, ARGS.out + '.done'
IDLE_MIN, WATCH_S = ARGS.idle, ARGS.watch
# 下面的坐标是物理像素，按作者电脑校准；界面布局或缩放不同时先手动量一下再改
NOTE_RECT = (329, 16, 1238, 889)          # 元宝笔记窗口固定到这个位置大小，下面的坐标都相对它
COPY_ARROW, COPY_MD = (1016, 136), (948, 219)
TOAST_BTN = (95, 60)                      # 「立即查看」相对弹窗窗口右下角
TOAST_CLASS = 'Qt680QWindowToolSaveBits'  # 弹窗的 Qt 窗口类名，客户端换 Qt 版本后可能会变
pyautogui.FAILSAFE = False


def idle_seconds():
    class LII(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
    li = LII(); li.cbSize = 8
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000


def physical_input_within(seconds):
    """挂低级键鼠钩子观察一段时间，返回期间有没有真人输入（排除程序注入的事件）。
    有些电脑上有程序一直在注入空输入，GetLastInputInfo 的空闲时间常年是 0，不能单用。"""
    import ctypes.wintypes as wt
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    seen = []
    HOOK = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
    u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
    u.CallNextHookEx.restype = ctypes.c_ssize_t
    u.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOK, ctypes.c_void_p, wt.DWORD]
    u.SetWindowsHookExW.restype = ctypes.c_void_p
    k.GetModuleHandleW.restype = ctypes.c_void_p

    def mk(flag_off, injected):
        def cb(code, wp, lp):
            if code == 0:
                flags = ctypes.cast(lp, ctypes.POINTER(wt.DWORD))[flag_off]
                if not flags & injected:
                    seen.append(wp)
            return u.CallNextHookEx(None, code, wp, lp)
        return HOOK(cb)
    # MSLLHOOKSTRUCT.flags 在第 4 个 DWORD（pt 占 2 个），KBDLLHOOKSTRUCT.flags 在第 3 个
    mcb, kcb = mk(3, 0x01), mk(2, 0x10)
    hm = u.SetWindowsHookExW(14, mcb, k.GetModuleHandleW(None), 0)
    hk = u.SetWindowsHookExW(13, kcb, k.GetModuleHandleW(None), 0)
    msg, end = wt.MSG(), time.time() + seconds
    while time.time() < end and not seen:
        while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            u.TranslateMessage(ctypes.byref(msg)); u.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.05)
    u.UnhookWindowsHookEx(ctypes.c_void_p(hm)); u.UnhookWindowsHookEx(ctypes.c_void_p(hk))
    return bool(seen)


def windows(title=None, cls=None):
    res = []
    def cb(h, _):
        if win32gui.IsWindowVisible(h) and (title is None or win32gui.GetWindowText(h) == title) \
                and (cls is None or win32gui.GetClassName(h) == cls):
            res.append(h)
    win32gui.EnumWindows(cb, None)
    return res


def uia_text(hwnd):
    """Qt 窗口的文字（UI Automation）；超时或失败返回空串。"""
    ps = ("Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes; "
          "$e=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]%d); "
          "$e.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)"
          " | %% { $_.Current.Name } | ? { $_ }" % hwnd)
    try:
        r = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                            '[Console]::OutputEncoding=[Text.Encoding]::UTF8; ' + ps],
                           capture_output=True, timeout=20, creationflags=0x08000000)
        return r.stdout.decode('utf-8', 'replace')
    except Exception:
        return ''


def click(x, y):
    pyautogui.moveTo(x, y, duration=0.2); time.sleep(0.1); pyautogui.click(); time.sleep(0.3)


def front(h):
    pyautogui.press('alt')
    try:
        win32gui.SetForegroundWindow(h)
    except Exception:
        pass
    time.sleep(0.4)


def grab():
    res = {'status': 'nothing', 'captured_at': int(time.time())}
    notes = windows('元宝笔记')
    toast, toast_text = None, ''
    if not notes:
        for h in windows('腾讯会议', TOAST_CLASS):
            t = uia_text(h)
            if '图文总结已生成' in t:
                toast, toast_text = h, t
                break
        if not toast:
            return res
    res['toast'] = toast_text
    idle = idle_seconds()
    if idle < IDLE_MIN and physical_input_within(WATCH_S):
        res.update(status='owner_active', idle=idle)
        return res
    prev_fg, prev_clip = win32gui.GetForegroundWindow(), pyperclip.paste()
    opened = False
    try:
        if not notes:
            l, t, r, b = win32gui.GetWindowRect(toast)
            click(r - TOAST_BTN[0], b - TOAST_BTN[1])
            for _ in range(30):
                time.sleep(0.5)
                notes = windows('元宝笔记')
                if notes:
                    break
            if not notes:
                res['status'] = 'toast_click_failed'
                return res
            opened = True
            time.sleep(4)                     # 等网页内容加载
        h = notes[0]
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
        win32gui.MoveWindow(h, *NOTE_RECT, True)
        front(h)
        md = ''
        for _ in range(3):
            pyperclip.copy('')
            click(NOTE_RECT[0] + COPY_ARROW[0], NOTE_RECT[1] + COPY_ARROW[1]); time.sleep(0.8)
            click(NOTE_RECT[0] + COPY_MD[0], NOTE_RECT[1] + COPY_MD[1]); time.sleep(1.5)
            md = pyperclip.paste()
            if md.lstrip().startswith('#'):
                break
            pyautogui.press('esc'); time.sleep(2)
        if md.lstrip().startswith('#'):
            res.update(status='ok', md=md, opened=opened)
        else:
            res.update(status='copy_failed', clip=md[:200])
        if opened:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
    finally:
        try:
            pyperclip.copy(prev_clip)
        except Exception:
            pass
        front(prev_fg)
    return res


if __name__ == '__main__':
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    for p in (OUT, DONE):
        if os.path.exists(p):
            os.remove(p)
    try:
        res = grab()
    except Exception:
        res = {'status': 'error', 'error': traceback.format_exc()[-1500:]}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False)
    open(DONE, 'w').write(res['status'])

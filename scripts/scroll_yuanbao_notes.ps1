param(
    [int]$PageDownCount = 90,
    [int]$DelayMs = 400,
    [string]$WindowTitlePattern = "*纪要*"
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class W32Scroll {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lp);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$wemeetProcessIds = @(Get-Process wemeetapp -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
if ($wemeetProcessIds.Count -eq 0) {
    throw "No wemeetapp process found. Open Tencent Meeting and the target Yuanbao notes page first."
}

$script:notesWindow = [IntPtr]::Zero
$callback = [W32Scroll+EnumWindowsProc]{
    param($hWnd, $lParam)

    [uint32]$processId = 0
    [W32Scroll]::GetWindowThreadProcessId($hWnd, [ref]$processId) | Out-Null
    if ($wemeetProcessIds -contains $processId -and [W32Scroll]::IsWindowVisible($hWnd)) {
        $titleBuilder = New-Object System.Text.StringBuilder 512
        [W32Scroll]::GetWindowText($hWnd, $titleBuilder, 512) | Out-Null
        if ($titleBuilder.ToString() -like $WindowTitlePattern) {
            $script:notesWindow = $hWnd
        }
    }

    return $true
}

[W32Scroll]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
if ($script:notesWindow -eq [IntPtr]::Zero) {
    throw "Yuanbao notes window not found. Open the target notes page and retry."
}

[W32Scroll]::ShowWindow($script:notesWindow, 9) | Out-Null
[W32Scroll]::SetForegroundWindow($script:notesWindow) | Out-Null
Start-Sleep -Seconds 1

$rect = New-Object W32Scroll+RECT
[W32Scroll]::GetWindowRect($script:notesWindow, [ref]$rect) | Out-Null
$centerX = [int](($rect.Left + $rect.Right) / 2)
$centerY = [int](($rect.Top + $rect.Bottom) / 2)
[W32Scroll]::SetCursorPos($centerX, $centerY) | Out-Null
Start-Sleep -Milliseconds 300

for ($i = 0; $i -lt $PageDownCount; $i++) {
    [System.Windows.Forms.SendKeys]::SendWait("{PGDN}")
    Start-Sleep -Milliseconds $DelayMs
}

Start-Sleep -Seconds 5
Write-Host "Scrolled Yuanbao notes window with $PageDownCount Page Down events."


param(
    [Parameter(Mandatory = $true)][string]$MeetingId,
    [Parameter(Mandatory = $true)][string]$RoomId,
    [Parameter(Mandatory = $true)][string]$MeetingStartTs,
    [int]$ExpectedNoteCount = 0,
    [string]$MeetingTitle = "Tencent Meeting",
    [string]$MeetingTimeRange = "",
    [string]$Participants = "",
    [string]$OutputFile = ".\output\realtime_notes.md",
    [hashtable]$UidMap = @{}
)

$ErrorActionPreference = "Stop"

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class MemX {
    [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(int a, bool b, int c);
    [DllImport("kernel32.dll")] public static extern bool ReadProcessMemory(IntPtr h, IntPtr addr, byte[] buf, int sz, out int read);
    [DllImport("kernel32.dll")] public static extern int VirtualQueryEx(IntPtr h, IntPtr addr, out MEMORY_BASIC_INFORMATION info, int len);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
    [StructLayout(LayoutKind.Sequential)]
    public struct MEMORY_BASIC_INFORMATION {
        public IntPtr BaseAddress; public IntPtr AllocationBase; public uint AllocationProtect;
        public IntPtr RegionSize; public uint State; public uint Protect; public uint Type;
    }
}
"@

$taskPrefix = "ainotes_task_ctt_uid:${MeetingStartTs}_${RoomId}_${MeetingId}_1_"
$cacheMarker = [char]0x5143 + [char]0x5B9D + [char]0x4F1A + [char]0x8BAE + [char]0x52A9 + [char]0x624B
$noteInfoRegex = [regex]::new('"note_info":\s*"((?:[^"\\]|\\.){20,})"', 'Compiled')
$timestampRegex = [regex]::new([regex]::Escape($taskPrefix) + '(\d+)_', 'Compiled')
$processIds = @(Get-Process wemeetapp -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id | Sort-Object -Unique)

if ($processIds.Count -eq 0) {
    throw "No wemeetapp process found. Open Tencent Meeting and the target Yuanbao notes page first."
}

$allNotes = @{}
$passStats = [ordered]@{
    pass1 = 0
    pass2 = 0
    pass3 = 0
}

function Test-ReadableProtection {
    param([uint32]$Protect)

    if (($Protect -band 0x100) -ne 0) {
        return $false
    }

    $basicProtect = $Protect -band 0xFF
    return $basicProtect -in @(0x02, 0x04, 0x08, 0x20, 0x40, 0x80)
}

function Add-NoteFromContext {
    param(
        [string]$Context,
        [string]$PassName
    )

    $timestampMatch = $timestampRegex.Match($Context)
    if (-not $timestampMatch.Success) {
        return $false
    }

    $noteMatch = $noteInfoRegex.Match($Context)
    if (-not $noteMatch.Success) {
        return $false
    }

    $generatedTimestamp = $timestampMatch.Groups[1].Value
    if ($allNotes.ContainsKey($generatedTimestamp)) {
        return $false
    }

    $allNotes[$generatedTimestamp] = $noteMatch.Groups[1].Value
    $passStats[$PassName]++
    return $true
}

function Invoke-MemoryPass {
    param(
        [string]$PassName,
        [scriptblock]$RegionProcessor
    )

    Write-Host "Running $PassName ..."

    foreach ($processId in $processIds) {
        if ($ExpectedNoteCount -gt 0 -and $allNotes.Count -ge $ExpectedNoteCount) {
            break
        }

        $handle = [MemX]::OpenProcess(0x0410, $false, $processId)
        if ($handle -eq [IntPtr]::Zero) {
            continue
        }

        $address = [IntPtr]::Zero
        $regions = 0

        try {
            while ($true) {
                $info = New-Object MemX+MEMORY_BASIC_INFORMATION
                $queryResult = [MemX]::VirtualQueryEx($handle, $address, [ref]$info, [System.Runtime.InteropServices.Marshal]::SizeOf($info))
                if ($queryResult -eq 0) {
                    break
                }

                $size = $info.RegionSize.ToInt64()
                if ($size -le 0 -or $size -gt 100MB) {
                    $address = [IntPtr]($address.ToInt64() + [Math]::Max($size, 4096))
                    continue
                }

                if ($info.State -eq 0x1000 -and (Test-ReadableProtection -Protect $info.Protect)) {
                    $regions++
                    try {
                        $buffer = New-Object byte[] $size
                        $bytesRead = 0
                        if ([MemX]::ReadProcessMemory($handle, $info.BaseAddress, $buffer, $size, [ref]$bytesRead) -and $bytesRead -gt 0) {
                            $text = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $bytesRead)
                            & $RegionProcessor $text
                        }
                    }
                    catch {
                    }
                }

                $address = [IntPtr]($address.ToInt64() + $size)

                if ($ExpectedNoteCount -gt 0 -and $allNotes.Count -ge $ExpectedNoteCount) {
                    break
                }
            }
        }
        finally {
            [MemX]::CloseHandle($handle) | Out-Null
        }

        Write-Host "  PID $processId scanned regions: $regions, notes so far: $($allNotes.Count)"
    }

    Write-Host "After ${PassName}: $($allNotes.Count) notes"
}

Invoke-MemoryPass -PassName "pass1(task_id proximity)" -RegionProcessor {
    param($text)

    $index = 0
    while (($index = $text.IndexOf($taskPrefix, $index, [System.StringComparison]::Ordinal)) -ge 0) {
        $contextStart = [Math]::Max(0, $index - 1000)
        $contextEnd = [Math]::Min($text.Length, $index + 20000)
        $context = $text.Substring($contextStart, $contextEnd - $contextStart)
        [void](Add-NoteFromContext -Context $context -PassName "pass1")
        $index += $taskPrefix.Length
    }
}

if ($ExpectedNoteCount -le 0 -or $allNotes.Count -lt $ExpectedNoteCount) {
    Invoke-MemoryPass -PassName "pass2(note_insight_info blocks)" -RegionProcessor {
        param($text)

        if (-not $text.Contains($MeetingId) -or -not $text.Contains("note_insight_info")) {
            return
        }

        $searchKey = "note_insight_info"
        $index = 0
        while (($index = $text.IndexOf($searchKey, $index, [System.StringComparison]::Ordinal)) -ge 0) {
            $contextStart = [Math]::Max(0, $index - 1500)
            $contextEnd = [Math]::Min($text.Length, $index + 6000)
            $context = $text.Substring($contextStart, $contextEnd - $contextStart)
            if ($context.Contains($MeetingId)) {
                [void](Add-NoteFromContext -Context $context -PassName "pass2")
            }
            $index += $searchKey.Length
        }
    }
}

if ($ExpectedNoteCount -le 0 -or $allNotes.Count -lt $ExpectedNoteCount) {
    Invoke-MemoryPass -PassName "pass3(render cache marker)" -RegionProcessor {
        param($text)

        if (-not $text.Contains($MeetingId) -or -not $text.Contains($cacheMarker)) {
            return
        }

        $index = 0
        while (($index = $text.IndexOf($cacheMarker, $index, [System.StringComparison]::Ordinal)) -ge 0) {
            $contextStart = [Math]::Max(0, $index - 800)
            $contextEnd = [Math]::Min($text.Length, $index + 8000)
            $context = $text.Substring($contextStart, $contextEnd - $contextStart)
            if ($context.Contains($MeetingId)) {
                [void](Add-NoteFromContext -Context $context -PassName "pass3")
            }
            $index += $cacheMarker.Length
        }
    }
}

$sortedNotes = $allNotes.GetEnumerator() | Sort-Object { [decimal]$_.Key }
$formattedBlocks = @()
$noteNumber = 1

foreach ($entry in $sortedNotes) {
    $decoded = $entry.Value -replace '\\n', "`n" -replace '\\t', "`t" -replace '\\"', '"' -replace '\\\\', '\'
    $decoded = $decoded -replace '\*\*', ''
    foreach ($uid in $UidMap.Keys) {
        $decoded = $decoded -replace "@@\($uid\)@@", $UidMap[$uid]
    }
    $decoded = $decoded -replace '@@\(\d+\)@@', ''
    $decoded = $decoded.Trim()

    $timestamp = [decimal]$entry.Key
    $milliseconds = [long]($timestamp / 1000000)
    try {
        $noteTime = [DateTimeOffset]::FromUnixTimeMilliseconds($milliseconds).ToLocalTime()
        $timeLabel = $noteTime.ToString('HH:mm')
    }
    catch {
        $timeLabel = "??:??"
    }

    $formattedBlocks += "### [$timeLabel] 纪要片段 $noteNumber`n`n$decoded`n"
    $noteNumber++
}

$statusLine = if ($ExpectedNoteCount -gt 0) {
    if ($allNotes.Count -ge $ExpectedNoteCount) {
        "- 提取状态: 已达到预期条数"
    }
    else {
        "- 提取状态: 未达到预期条数；请重新打开元宝纪要页面，完整滚动后再重跑"
    }
}
else {
    "- 提取状态: 已完成扫描；未提供已验证的预期总条数"
}

$countLine = if ($ExpectedNoteCount -gt 0) {
    "- 纪要条数: $($allNotes.Count)/$ExpectedNoteCount"
}
else {
    "- 纪要条数: $($allNotes.Count)"
}

$header = @"
# $MeetingTitle - 元宝实时纪要

- 会议时间: $MeetingTimeRange
- 参会人: $Participants
- 提取时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm')
$countLine
$statusLine

---

"@

$resolvedOutputFile = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputFile))
$outputDir = Split-Path -Parent $resolvedOutputFile
if ($outputDir -and -not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}

[System.IO.File]::WriteAllText($resolvedOutputFile, $header + ($formattedBlocks -join "`n"), [System.Text.UTF8Encoding]::new($false))

Write-Host "各轮提取贡献:"
Write-Host "  pass1(task_id proximity): $($passStats.pass1)"
Write-Host "  pass2(note_insight_info blocks): $($passStats.pass2)"
Write-Host "  pass3(render cache marker): $($passStats.pass3)"
Write-Host "已保存 $($allNotes.Count) 条纪要到 $resolvedOutputFile"

if ($ExpectedNoteCount -gt 0 -and $allNotes.Count -lt $ExpectedNoteCount) {
    Write-Warning "只提取到 $($allNotes.Count)/$ExpectedNoteCount 条。剩余内容可能尚未加载进渲染进程内存。"
}

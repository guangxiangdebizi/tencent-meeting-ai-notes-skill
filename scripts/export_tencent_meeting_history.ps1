param(
    [Parameter(Mandatory = $true)][string]$DatabasePath,
    [string]$OutputRoot = ".\output",
    [string]$SqliteExe = "sqlite3"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $DatabasePath)) {
    throw "Tencent Meeting database not found: $DatabasePath"
}

if (-not (Get-Command $SqliteExe -ErrorAction SilentlyContinue)) {
    throw "sqlite3 executable not found. Pass -SqliteExe with the full path to sqlite3.exe."
}

function Invoke-SqliteCsv {
    param(
        [string]$DatabasePath,
        [string]$Sql
    )

    $raw = & $SqliteExe -header -csv $DatabasePath $Sql
    if (-not $raw) {
        return @()
    }

    return $raw | ConvertFrom-Csv
}

$outputMetaDir = Join-Path $OutputRoot "metadata"
New-Item -ItemType Directory -Force -Path $outputMetaDir | Out-Null

$allMeetings = Invoke-SqliteCsv -DatabasePath $DatabasePath -Sql @"
select
  id,
  meeting_subject,
  meeting_code,
  datetime(meeting_begin_time, 'unixepoch', 'localtime') as begin_time,
  creator_nickname,
  has_ai_summary,
  ai_summary_num
from historical_meetings_new
order by meeting_begin_time desc;
"@

$allMeetings | Export-Csv -LiteralPath (Join-Path $outputMetaDir "all_meetings.csv") -NoTypeInformation -Encoding UTF8
$meetingsWithSummary = @($allMeetings | Where-Object { $_.has_ai_summary -eq "1" })

$summary = @"
# 腾讯会议历史元数据导出

- 全部会议数: $($allMeetings.Count)
- 带 AI 纪要标记的会议数: $($meetingsWithSummary.Count)
- 元数据 CSV: metadata/all_meetings.csv

这个导出只包含本地会议元数据。如果生成结果里包含真实会议主题、会议号或参会人姓名，不要提交到公开仓库。
"@

Set-Content -LiteralPath (Join-Path $OutputRoot "README.md") -Value $summary -Encoding UTF8
Write-Host "已导出 $($allMeetings.Count) 条会议元数据到 $OutputRoot"

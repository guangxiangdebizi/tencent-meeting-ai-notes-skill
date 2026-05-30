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
# Tencent Meeting History Export

- Total meetings: $($allMeetings.Count)
- Meetings with AI summary flag: $($meetingsWithSummary.Count)
- Metadata CSV: metadata/all_meetings.csv

This export contains local metadata only. Do not commit generated output if it includes real meeting subjects, meeting codes, or participant names.
"@

Set-Content -LiteralPath (Join-Path $OutputRoot "README.md") -Value $summary -Encoding UTF8
Write-Host "Exported $($allMeetings.Count) meeting metadata rows to $OutputRoot"


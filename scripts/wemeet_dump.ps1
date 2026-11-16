# 扫描腾讯会议 wemeetapp 全部进程内存，导出元宝纪要 note_info 片段和会议主题 URL（只读）
param(
  [string]$Out = ".\output\raw\dump.jsonl.gz",
  [int]$Tail = 4000
)
$ErrorActionPreference = "Stop"
if (-not ([System.Management.Automation.PSTypeName]'WmDump').Type) {
Add-Type -ReferencedAssemblies System -TypeDefinition @"
using System; using System.IO; using System.Text; using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class WmDump {
  [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(int a, bool b, int c);
  [DllImport("kernel32.dll")] static extern bool ReadProcessMemory(IntPtr h, IntPtr addr, byte[] buf, IntPtr sz, out IntPtr read);
  [DllImport("kernel32.dll")] static extern int VirtualQueryEx(IntPtr h, IntPtr addr, out MBI info, int len);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] struct MBI { public IntPtr BaseAddress; public IntPtr AllocationBase; public uint AllocationProtect; public IntPtr RegionSize; public uint State; public uint Protect; public uint Type; }
  static int IndexOf(byte[] hay, int len, byte[] nd, int start) {
    int n = nd.Length; byte f = nd[0];
    for (int i = start; i <= len - n; i++) { if (hay[i] != f) continue; int j = 1; while (j < n && hay[i+j] == nd[j]) j++; if (j == n) return i; }
    return -1;
  }
  static string Esc(string s) {
    var sb = new StringBuilder(s.Length + 16);
    foreach (char c in s) {
      if (c == '"') sb.Append("\\\""); else if (c == '\\') sb.Append("\\\\");
      else if (c < 0x20) sb.Append(' '); else sb.Append(c);
    }
    return sb.ToString();
  }
  public static int Dump(int[] pids, string outPath, int tail) {
    var kNote = Encoding.UTF8.GetBytes("\"note_info\": \"");
    var kSubj = Encoding.UTF8.GetBytes("&meeting_subject=");
    var seen = new HashSet<string>(); int n = 0;
    using (var fs = File.Create(outPath)) using (var gz = new System.IO.Compression.GZipStream(fs, System.IO.Compression.CompressionMode.Compress)) using (var w = new StreamWriter(gz, new UTF8Encoding(false))) {
      foreach (int pid in pids) {
        IntPtr h = OpenProcess(0x0410, false, pid); if (h == IntPtr.Zero) continue;
        try {
          long addr = 0; MBI m;
          while (VirtualQueryEx(h, new IntPtr(addr), out m, Marshal.SizeOf(typeof(MBI))) != 0) {
            long size = m.RegionSize.ToInt64(); if (size <= 0) break;
            uint bp = m.Protect & 0xFF;
            bool ok = m.State == 0x1000 && (m.Protect & 0x100) == 0 && (bp==0x02||bp==0x04||bp==0x08||bp==0x20||bp==0x40||bp==0x80);
            if (ok && size <= 512L*1024*1024) {
              byte[] buf = new byte[size]; IntPtr rd;
              if (ReadProcessMemory(h, m.BaseAddress, buf, new IntPtr(size), out rd) && rd.ToInt64() > 0) {
                int len = (int)rd.ToInt64(); int pos = 0;
                while ((pos = IndexOf(buf, len, kNote, pos)) >= 0) {
                  int s = pos + kNote.Length, e = s;
                  while (e < len && e - s < 400000) { byte b = buf[e]; if (b == (byte)'\\') { e += 2; continue; } if (b == (byte)'"' || b < 0x0a) break; e++; }
                  if (e >= len) e = len;
                  string val = Encoding.UTF8.GetString(buf, s, e - s);
                  int te = Math.Min(len, e + tail);
                  string tl = Encoding.UTF8.GetString(buf, e, te - e);
                  int hs = Math.Max(0, pos - 200);
                  string hd = Encoding.UTF8.GetString(buf, hs, pos - hs);
                  string key = val + "\u0001" + tl.Substring(0, Math.Min(tl.Length, 600));
                  if (seen.Add(key)) { w.WriteLine("{\"t\":\"note\",\"pid\":" + pid + ",\"term\":" + (e < len && buf[e] == (byte)'"' ? "true" : "false") + ",\"v\":\"" + Esc(val) + "\",\"tail\":\"" + Esc(tl) + "\",\"head\":\"" + Esc(hd) + "\"}"); n++; }
                  pos = e;
                }
                pos = 0;
                while ((pos = IndexOf(buf, len, kSubj, pos)) >= 0) {
                  int s = Math.Max(0, pos - 120), e = pos;
                  while (e < len && e - pos < 600 && buf[e] > 0x20) e++;
                  string u = Encoding.UTF8.GetString(buf, s, e - s);
                  if (seen.Add(u)) { w.WriteLine("{\"t\":\"url\",\"pid\":" + pid + ",\"v\":\"" + Esc(u) + "\"}"); n++; }
                  pos = e;
                }
              }
            }
            addr = m.BaseAddress.ToInt64() + size;
          }
        } finally { CloseHandle(h); }
      }
    }
    return n;
  }
}
"@
}
$pids = [int[]]@(Get-Process wemeetapp -ea 0 | % Id)
if ($pids.Count -eq 0) { Write-Output "NO_WEMEET_PROCESS"; exit 2 }
# .NET 的当前目录不跟 PowerShell 走，先转成绝对路径
$Out = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Out)
$dir = Split-Path $Out; if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
$n = [WmDump]::Dump($pids, $Out, $Tail)
Write-Output "DUMPED $n records from $($pids.Count) processes -> $Out"

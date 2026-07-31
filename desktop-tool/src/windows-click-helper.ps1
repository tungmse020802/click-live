$ErrorActionPreference = "Stop"

$sig = @'
[DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint cButtons, uint dwExtraInfo);
'@

$null = Add-Type -MemberDefinition $sig -Name WinMouse -Namespace ClickLive -PassThru

[Console]::Out.WriteLine("ready")
[Console]::Out.Flush()

while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  $line = $line.Trim()
  if ($line -eq "quit") { break }
  if ($line -match '^(-?\d+),(-?\d+)$') {
    $x = [int]$Matches[1]
    $y = [int]$Matches[2]
    [ClickLive.WinMouse]::SetCursorPos($x, $y) | Out-Null
    [ClickLive.WinMouse]::mouse_event(0x0002, 0, 0, 0, 0)
    [ClickLive.WinMouse]::mouse_event(0x0004, 0, 0, 0, 0)
    [Console]::Out.WriteLine("ok")
  } else {
    [Console]::Out.WriteLine("err")
  }
  [Console]::Out.Flush()
}

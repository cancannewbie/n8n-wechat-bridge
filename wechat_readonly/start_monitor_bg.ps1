$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$pyw = "C:\Users\Administrator\AppData\Local\Programs\Python\Python313\pythonw.exe"
$py  = "C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }

# kill existing monitors
$pidFile = Join-Path $PSScriptRoot "state\monitor.pid"
if (Test-Path $pidFile) {
  $old = (Get-Content $pidFile -Raw).Trim()
  if ($old) { Stop-Process -Id ([int]$old) -Force -ErrorAction SilentlyContinue }
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
Get-CimInstance Win32_Process -Filter "name='python.exe' OR name='pythonw.exe'" |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'monitor\.py') } |
  ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "[wechat_readonly] stopped old monitor PID $($_.ProcessId)"
  }

Write-Host "[wechat_readonly] starting monitor hidden (pythonw) ..."
$p = Start-Process -FilePath $pyw -ArgumentList "monitor.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 2
if (Test-Path $pidFile) {
  $np = (Get-Content $pidFile -Raw).Trim()
  Write-Host "[wechat_readonly] monitor running PID $np (no window)"
} elseif ($p -and -not $p.HasExited) {
  Write-Host "[wechat_readonly] monitor process $($p.Id) started (pid file pending)"
} else {
  Write-Host "[wechat_readonly] WARNING: monitor may have exited; check logs\monitor.log"
  if (Test-Path (Join-Path $PSScriptRoot "logs\monitor.log")) {
    Get-Content (Join-Path $PSScriptRoot "logs\monitor.log") -Tail 20
  }
}
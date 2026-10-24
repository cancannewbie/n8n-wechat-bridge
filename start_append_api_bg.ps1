$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$pyw = "C:\Users\Administrator\AppData\Local\Programs\Python\Python313\pythonw.exe"
$py  = "C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe"
if (-not (Test-Path $pyw)) { $pyw = $py }

$listening = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
  Write-Host "[n8n-wechat-bridge] append_api already listening on :8787"
  exit 0
}

# kill any orphaned append_api then start hidden
Get-CimInstance Win32_Process -Filter "name='python.exe' OR name='pythonw.exe'" |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'append_api\.py') } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "[n8n-wechat-bridge] starting excel append API on :8787 (hidden) ..."
& $py -m pip install -r requirements.txt -q 2>$null | Out-Null
Start-Process -FilePath $pyw -ArgumentList "append_api.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden | Out-Null
Start-Sleep -Seconds 2
$listening = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
  Write-Host "[n8n-wechat-bridge] append_api listening on :8787 (no window)"
} else {
  Write-Host "[n8n-wechat-bridge] start issued; check logs\append_api.log if port not up"
}
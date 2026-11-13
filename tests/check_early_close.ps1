param([Parameter(Mandatory=$true)][string]$Folder,[Parameter(Mandatory=$true)][string]$Cache,[Parameter(Mandatory=$true)][string]$Report)
$ErrorActionPreference='Stop'
$root=(Resolve-Path -LiteralPath $Folder).Path
$expected=[IO.Path]::GetFullPath((Join-Path $root '程序文件/界面.exe'))
$log=Join-Path $root '程序文件/results/桌面窗口.log'
if (Test-Path -LiteralPath $log) { Remove-Item -LiteralPath $log }
$env:PENDULUM_TEST_CACHE_ROOT=(Resolve-Path -LiteralPath $Cache).Path
Start-Process -FilePath (Join-Path $root '倒立摆.exe') -WorkingDirectory $root -WindowStyle Hidden
$deadline=[DateTime]::UtcNow.AddSeconds(30)
$hostProcess=$null
while ([DateTime]::UtcNow -lt $deadline) {
    $hostProcess=Get-Process -Name '界面' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $expected -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if ($hostProcess) { break }
    Start-Sleep -Milliseconds 10
}
if (!$hostProcess) { throw 'No actual startup window' }
if (Test-Path -LiteralPath $log) { throw 'Missed startup-close interval' }
if (!$hostProcess.CloseMainWindow()) { throw 'Could not close actual startup window' }
if (!$hostProcess.WaitForExit(60000)) { throw 'Hidden startup host failed to exit' }
Start-Sleep -Milliseconds 500
$instance=Get-Content -LiteralPath (Join-Path $root '程序文件/.cache/instance.json') -Raw | ConvertFrom-Json
$backend=Get-Process -Id $instance.pid -ErrorAction SilentlyContinue
if ($backend -and $backend.Path.StartsWith($env:PENDULUM_TEST_CACHE_ROOT+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Startup close orphaned its server' }
@{passed=$true;actual_exe=$root;closed_before_page_navigation=$true;host_exited=$true;own_backend_exited=$true} | ConvertTo-Json | Set-Content -LiteralPath $Report -Encoding utf8
Write-Output 'PASS close during actual startup; no orphan backend'

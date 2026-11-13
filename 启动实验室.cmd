@echo off
cd /d "%~dp0"
if exist "dist\current.json" (
  powershell -NoProfile -WindowStyle Hidden -Command "$r=Get-Content -Raw -Encoding UTF8 'dist\current.json' | ConvertFrom-Json; $d=Join-Path (Get-Location).Path ('dist\'+$r.folder); if($r.entry){Start-Process -FilePath (Join-Path $d $r.entry) -WorkingDirectory $d}else{Start-Process -FilePath (Join-Path $d 'runtime\pythonw.exe') -ArgumentList 'launch.py' -WorkingDirectory $d -WindowStyle Hidden}"
  exit /b
)
if exist "runtime\pythonw.exe" (
  start "" /b "runtime\pythonw.exe" "launch.py"
) else (
  python "launch.py"
)

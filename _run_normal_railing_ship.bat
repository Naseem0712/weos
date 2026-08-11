@echo off
cd /d "d:\Downloads\window cad model"
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Public\weos_smoke_commit.ps1"
type C:\Users\Public\weos_report.txt
pause

@echo off
setlocal
cd /d "D:\Downloads\window cad model"
echo === ADD ===
git add -- "WEOS/api/server.py" "WEOS/db/models.py" "WEOS/factory/company_workspace.py" "WEOS/factory/customer_store.py" "WEOS/factory/ledger_pdf.py" "WEOS/factory/ledger_store.py" "WEOS/factory/project_store.py" "WEOS/website/index.html" "WEOS/_smoke_gst_hub_persist.py"
echo === STAGED ===
git diff --cached --stat
echo === COMMIT ===
git commit -F "_commit_msg.txt"
set EC=%ERRORLEVEL%
echo COMMIT_EXIT=%EC%
git status -sb
git rev-parse HEAD
if not %EC%==0 exit /b %EC%
echo === PUSH ===
git push origin main
set PE=%ERRORLEVEL%
echo PUSH_EXIT=%PE%
if not %PE%==0 exit /b %PE%
echo PUSH_DONE

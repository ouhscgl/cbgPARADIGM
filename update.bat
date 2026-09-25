@echo off
setlocal
cd /d "%~dp0"

echo Checking this machine for local edits...
git diff --quiet HEAD
if errorlevel 1 (
    echo.
    echo *** This copy has edits that are not in the repository: ***
    git status --short --untracked-files=no
    echo.
    echo Nothing has been changed.
    echo.
    echo If those edits are in configs\, they belong in an untracked overlay
    echo instead - move them out once and updates will never clash again:
    echo   python auxfunc\config.py --extract settings.json --write
    echo   python auxfunc\config.py --extract profiles.json --write
    echo   git checkout -- configs
    echo.
    echo Otherwise: git stash (keep them^) or git checkout -- . (discard them^),
    echo then run this again.
    pause
    exit /b 1
)

echo Fetching...
git fetch --tags --prune
if errorlevel 1 (
    echo Could not reach GitHub. Nothing changed.
    pause
    exit /b 1
)

git pull --ff-only
if errorlevel 1 (
    echo.
    echo The update is not a fast-forward, so nothing was changed.
    echo This copy has commits that are not on the server.
    pause
    exit /b 1
)

python -c "from auxfunc.version import describe; print('Now running', describe())"
echo.
pause

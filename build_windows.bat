@echo off
setlocal

py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

pyinstaller --noconfirm --clean --onefile --windowed ^
  --name SkylineDock ^
  --additional-hooks-dir=. ^
  main.py

echo.
echo Build complete: dist\SkylineDock.exe
pause

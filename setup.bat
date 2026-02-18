@echo off
echo === Leads Generator Setup ===

echo [1/4] Creating virtual environment...
python -m venv .venv

echo [2/4] Activating virtual environment...
call .venv\Scripts\activate.bat

echo [3/4] Installing dependencies...
pip install -r requirements.txt

echo [4/4] Installing Playwright browsers...
playwright install chromium

echo.
echo === Setup complete! ===
echo.
echo Next steps:
echo   1. Edit .env and add your SNOV_CLIENT_SECRET
echo   2. Run now:       python main.py --now
echo   3. Check status:  python main.py --status
echo   4. Start daily:   python main.py
echo.
pause

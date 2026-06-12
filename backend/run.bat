@echo off
REM Medical CAT Translator — Windows launcher
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
echo.
echo  ===========================================================
echo   Medical CAT Translator v5.5
echo   http://localhost:8000
echo   Default password: medtranslator2026
echo  ===========================================================
echo.
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

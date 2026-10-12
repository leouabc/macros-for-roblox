@echo off
cd /d "%~dp0"
python -m pip install --quiet -r requirements.txt
python macro_dulces.py
if errorlevel 1 pause

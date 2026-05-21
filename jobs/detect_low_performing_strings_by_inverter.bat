@echo off
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
python -m scripts.detect_low_performing_strings_by_inverter
@echo off
cd /d C:\tera-spms

call .venv\Scripts\activate
python -m scripts.generate_low_psh_generation_report
pause
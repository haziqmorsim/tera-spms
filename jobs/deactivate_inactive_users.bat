@echo off
cd /d C:\tera-spms

call .venv\Scripts|Activate
python -m scripts.deactivate_inactive_users
pause
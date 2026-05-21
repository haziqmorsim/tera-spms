@echo off
cd /d C:\tera-spms

echo ==== START %date% %time% ==== >> logs\poll_alarms.log
echo CD=%cd% >> logs\poll_alarms.log

C:\tera-spms\.venv\Scripts\python.exe -m scripts.poll_alarms >> logs\poll_alarms.log 2>&1

echo === END %date% %time% ==== >> logs\poll_alarms.log
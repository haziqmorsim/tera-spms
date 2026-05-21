@echo off
cd /d C:\tera-spms
echo ==== START %date% %time% ==== >> logs\sync_high_temperature_inverters.log
echo CD=%cd% >> logs\sync_high_temperature_inverters.log

C:\tera-spms\.venv\Scripts\python.exe -m scripts.sync_high_temperature_inverters >> logs\sync_high_temperature_inverters.log 2>&1

echo ==== END %date% %time% ==== >> logs\sync_high_temperature_inverters.log
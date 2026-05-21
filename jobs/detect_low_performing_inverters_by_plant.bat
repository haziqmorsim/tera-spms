@echo off
cd /d C:\tera-spms

if not exist logs mkdir logs

echo ==== START %date% %time% ==== >> logs\detect_low_performing_inverters_by_plant.log
echo CD=%cd% >> logs\detect_low_performing_inverters_by_plant.log

C:\tera-spms\.venv\Scripts\python.exe -m scripts.detect_low_performing_inverters_by_plant >> logs\detect_low_performing_inverters_by_plant.log 2>&1

echo ==== END %date% %time% ==== >> logs\detect_low_performing_inverters_by_plant.log
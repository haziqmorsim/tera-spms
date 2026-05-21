@echo off
cd /d C:\tera-spms

echo ==== START %date% %time% ==== >> logs\detect_low_psh_plants_by_city.log
echo CD=%cd% >> logs\detect_low_psh_plants_by_city.log

C:\tera-spms\.venv\Scripts\python.exe -m scripts.detect_low_psh_plants_by_city >> logs\detect_low_psh_plants_by_city.log 2>&1

echo ==== END %date% %time% ==== >> logs\detect_low_psh_plants_by_city.log
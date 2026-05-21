@echo off
cd /d C:\tera-spms

echo ==== START %date% %time% ==== >> logs\generate_troubleshooting_pdf.log
echo CD=%cd% >> logs\generate_troubleshooting_pdf.log

C:\tera-spms\.venv\Scripts\python.exe -m scripts.generate_troubleshooting_pdf >> logs\generate_troubleshooting_pdf.log 2>&1

echo ==== END %date% %time% ==== >> logs\generate_troubleshooting_pdf.log
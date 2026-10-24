@echo off
cd /d C:\n8n-wechat-bridge\wechat_readonly
"C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe" -c "import json;p=r'config.json';d=json.load(open(p,encoding='utf-8'));d['dry_run']=True;json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)"
"C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe" monitor.py
pause
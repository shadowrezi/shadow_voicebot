import re
d=open(r"C:\Users\shadowrezi\Documents\Code\jarvis\jarvis\tools.py",encoding="utf-8").read()
for line in d.splitlines():
    if "firefox" in line.lower() or "fайрфокс" in line.lower():
        print(line.strip())

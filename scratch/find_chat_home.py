import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('chat/views.py', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

import re

for m in re.finditer(r'def chat_home\(', text):
    start = m.start()
    lines = text[start:start+6000].splitlines()
    print("\n".join(lines[85:170]))

import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

import re

matches = [m.start() for m in re.finditer(r'session_type', text)]
print(f"session_type occurrences: {len(matches)}")
for pos in matches:
    line_num = text[:pos].count('\n') + 1
    print(f"Line {line_num}: {text[pos-30:pos+80].strip()}")

import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

import re

# Find chat-flow opening
cf_pos = text.find('id="chat-flow"')
print("chat-flow opening:", cf_pos)
chunk = text[cf_pos:cf_pos+2000]
print(chunk[:1000])

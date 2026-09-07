import re
import subprocess
import tempfile
import os

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    content = f.read()

scripts = re.findall(r'<script(?:\s+[^>]*)?>(.*?)</script>', content, flags=re.DOTALL)
print(f'Total script tags found: {len(scripts)}')

has_err = False
for idx, s in enumerate(scripts):
    if not s.strip():
        continue
    # Replace django tags
    sanitized = re.sub(r'\{%.*?%\}', '/* django */', s)
    sanitized = re.sub(r'\{\{.*?\}\}', '0', sanitized)
    
    with tempfile.NamedTemporaryFile(suffix='.js', delete=False, mode='w', encoding='utf-8') as tf:
        tf.write(sanitized)
        tf_name = tf.name
    
    res = subprocess.run(['node', '--check', tf_name], capture_output=True, text=True)
    os.remove(tf_name)
    if res.returncode != 0:
        print(f'Script #{idx+1} has syntax error:\n{res.stderr[:300]}')
        has_err = True

if not has_err:
    print('ALL inline scripts in templates/chat.html pass node --check syntax validation!')

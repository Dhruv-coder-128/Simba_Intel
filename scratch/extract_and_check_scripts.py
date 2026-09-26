import re
import os
import subprocess

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Match script tags without src
script_pattern = re.compile(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
matches = script_pattern.findall(html)

print(f"Found {len(matches)} inline script blocks.")

for idx, code in enumerate(matches, 1):
    if not code.strip():
        continue
    # Replace Django template tags like {{ ... }}, {% ... %} with valid JS to test pure JS syntax
    clean_code = re.sub(r'\{%.*?%\}', '/* dj */', code)
    clean_code = re.sub(r'\{\{.*?\}\}', '"dj_var"', clean_code)

    filename = f'scratch/test_script_{idx}.js'
    with open(filename, 'w', encoding='utf-8') as sf:
        sf.write(clean_code)

    res = subprocess.run(['node', '--check', filename], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"Script {idx} ({len(code)} chars): SYNTAX OK")
    else:
        print(f"Script {idx} ({len(code)} chars): SYNTAX ERROR:")
        print(res.stderr[:500])

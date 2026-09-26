import re
import subprocess

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    html = f.read()

script_pattern = re.compile(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
matches = script_pattern.findall(html)

for idx, code in enumerate(matches, 1):
    cleaned = re.sub(r'\"\{\{.*?\}\}\"', '\"str_val\"', code)
    cleaned = re.sub(r'\'\{\{.*?\}\}\'', '\'str_val\'', cleaned)
    cleaned = re.sub(r'\{\{.*?\}\}', '123', cleaned)
    cleaned = re.sub(r'\{%.*?%\}', '/* dj */', cleaned)

    filename = f'scratch/test_script_clean_{idx}.js'
    with open(filename, 'w', encoding='utf-8') as sf:
        sf.write(cleaned)

    res = subprocess.run(['node', '--check', filename], capture_output=True, text=True)
    if res.returncode == 0:
        print(f'Script {idx}: SYNTAX OK')
    else:
        print(f'Script {idx}: SYNTAX ERROR:')
        print(res.stderr[:800])

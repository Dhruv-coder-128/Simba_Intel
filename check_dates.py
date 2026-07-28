import os, re
found = False
for root, dirs, files in os.walk(r'd:\dhruv\Simba_Intel - Copy\templates'):
    for f in files:
        if f.endswith('.html'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as file:
                content = file.read()
                unwrapped = []
                parts = content.split('<time')
                for part in parts:
                    if '</time>' in part:
                        outside = part.split('</time>', 1)[1]
                    else:
                        outside = part
                    out_matches = re.findall(r'\{\{\s*[a-zA-Z0-9_\.]+\|date:\"[^\"]+\"[^\}]*\}\}', outside)
                    if out_matches:
                        unwrapped.extend(out_matches)
                if unwrapped:
                    print(f'Found in {f}: {unwrapped}')
                    found = True
if not found: print('All clear!')

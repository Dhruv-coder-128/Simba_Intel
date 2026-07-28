import os
import re

files = [
    r'templates\admin_console\user_detail.html',
    r'templates\admin_console\users_list.html',
    r'templates\admin_console\security.html',
    r'templates\admin_console\feature_flags.html',
    r'templates\admin_console\errors.html',
    r'templates\admin_console\dashboard.html',
    r'templates\admin_console\broadcasts.html',
    r'templates\admin_console\audit_log.html'
]

for file in files:
    path = os.path.join(r'd:\dhruv\Simba_Intel - Copy', file)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    def repl(m):
        full = m.group(0)
        var = m.group(1)
        fmt = m.group(2)
        
        data_format = 'datetime-short'
        if 'Y H:i:s' in fmt:
            data_format = 'datetime-long'
        elif 'H:i' not in fmt:
            data_format = 'date'
            
        datetime_attr = '{{ ' + var + '|date:\'c\' }}'
        return f'<time class=\"local-time\" datetime=\"{datetime_attr}\" data-format=\"{data_format}\">{full}</time>'

    new_content = re.sub(r'\{\{\s*([a-zA-Z0-9_\.]+)\|date:(\"[^\"]+\")[^\}]*\}\}', repl, content)
    
    if new_content != content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f'Updated {file}')

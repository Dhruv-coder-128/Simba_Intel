import re

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    text = f.read()

pos_style_start = text.find('<style')
pos_style_end = text.find('</style>')

style_content = text[pos_style_start:pos_style_end]
start_line = text[:pos_style_start].count('\n') + 1

print(f"Style tag starts at line {start_line}, ends at line {text[:pos_style_end].count(chr(10))+1}")

# Check unclosed comments
comments_open = [m.start() for m in re.finditer(r'/\*', style_content)]
comments_close = [m.start() for m in re.finditer(r'\*/', style_content)]
print(f"/* count: {len(comments_open)}, */ count: {len(comments_close)}")

# Check brace matching
# Remove comments and strings before counting braces
clean_css = re.sub(r'/\*.*?\*/', '', style_content, flags=re.DOTALL)
clean_css = re.sub(r'"(?:\\.|[^"\\])*"', '', clean_css)
clean_css = re.sub(r"'(?:\\.|[^'\\])*'", '', clean_css)

open_braces = clean_css.count('{')
close_braces = clean_css.count('}')
print(f"Clean CSS: open braces: {open_braces}, close braces: {close_braces}, diff: {open_braces - close_braces}")

if open_braces != close_braces:
    count = 0
    lines = clean_css.split('\n')
    for idx, l in enumerate(lines):
        o = l.count('{')
        c = l.count('}')
        count += (o - c)
        if count < 0:
            print(f"Negative balance at relative line {idx+1}: {l.strip()}")
            break
    print(f"Final balance: {count}")

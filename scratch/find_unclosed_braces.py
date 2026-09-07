import re

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    text = f.read()

pos_style_start = text.find('<style')
pos_style_end = text.find('</style>')

style_content = text[pos_style_start:pos_style_end]
start_line = text[:pos_style_start].count('\n') + 1

# Split into lines and find brace nesting
lines = style_content.split('\n')
in_comment = False
balance = 0
unclosed_stack = []

for i, line in enumerate(lines):
    line_no = start_line + i
    # strip comments roughly for this line
    cleaned = ""
    idx = 0
    while idx < len(line):
        if not in_comment and line[idx:idx+2] == '/*':
            in_comment = True
            idx += 2
        elif in_comment and line[idx:idx+2] == '*/':
            in_comment = False
            idx += 2
        elif not in_comment:
            cleaned += line[idx]
            idx += 1
        else:
            idx += 1
    
    # ignore strings
    cleaned = re.sub(r'"(?:\\.|[^"\\])*"', '', cleaned)
    cleaned = re.sub(r"'(?:\\.|[^'\\])*'", '', cleaned)

    for ch in cleaned:
        if ch == '{':
            balance += 1
            unclosed_stack.append((line_no, line.strip()))
        elif ch == '}':
            balance -= 1
            if unclosed_stack:
                unclosed_stack.pop()

print(f"Final balance: {balance}")
print("Remaining unclosed braces on stack:")
for lno, ltext in unclosed_stack:
    print(f"Line {lno}: {ltext}")

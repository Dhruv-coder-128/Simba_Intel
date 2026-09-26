import re

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")

# 1. Check for unclosed {{ or {%
unclosed_django = []
for i, line in enumerate(lines, 1):
    # check unclosed on same line (unless multiline)
    if '{{' in line and '}}' not in line:
        unclosed_django.append((i, 'unclosed {{', line.strip()))
    if '{%' in line and '%}' not in line:
        unclosed_django.append((i, 'unclosed {%', line.strip()))

print(f"Django tag multiline/unclosed count: {len(unclosed_django)}")
for item in unclosed_django:
    print(item)

# 2. Check for double brackets like {{{ or }}}
bad_brackets = []
for i, line in enumerate(lines, 1):
    if '{{{' in line or '}}}' in line:
        bad_brackets.append((i, line.strip()))
print(f"Bad brackets count: {len(bad_brackets)}")
for item in bad_brackets[:10]:
    print(item)

# 3. Check for malformed tags like << or >> or < without >
malformed = []
for i, line in enumerate(lines, 1):
    if '<<' in line or '>>' in line:
        # Check if inside script (shift operator << or >> is valid in JS)
        pass


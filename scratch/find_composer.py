import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'id="user-input"' in line:
        print(f"user-input at line {i+1}")
        for j in range(max(0, i-15), min(len(lines), i+35)):
            print(f"{j+1}: {lines[j]}", end="")
        break

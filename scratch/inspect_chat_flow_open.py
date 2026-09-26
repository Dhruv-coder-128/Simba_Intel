import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

for i in range(10540, 10605):
    print(f"{i+1}: {lines[i]}", end="")

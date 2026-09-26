import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

print("--- VOICE JS (19400 - 19720) ---")
for i in range(19400, min(len(lines), 19720)):
    print(f"{i+1}: {lines[i]}", end="")

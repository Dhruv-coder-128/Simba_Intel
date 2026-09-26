import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

print("CSS at 6450-6465:")
for i in range(6449, 6465):
    print(f"{i+1}: {lines[i]}", end="")

print("\nCSS at 6720-6735:")
for i in range(6719, 6735):
    print(f"{i+1}: {lines[i]}", end="")

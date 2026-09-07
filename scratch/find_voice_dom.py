with open('templates/chat.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, l in enumerate(lines):
    if 'id="voiceWorkspace"' in l:
        print(f"voiceWorkspace found at line {i+1}")
        for j in range(i, min(len(lines), i+60)):
            print(f"{j+1}: {lines[j]}", end="")
        break

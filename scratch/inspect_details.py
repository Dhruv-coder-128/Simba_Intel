with open('templates/chat.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines in chat.html: {len(lines)}")
print("\n--- Inspecting CSS lines 7760 to 7820 ---")
for i in range(7759, min(7820, len(lines))):
    print(f"{i+1}: {lines[i]}", end="")

print("\n\n--- Inspecting CSS lines 8980 to 9030 ---")
for i in range(8979, min(9030, len(lines))):
    print(f"{i+1}: {lines[i]}", end="")

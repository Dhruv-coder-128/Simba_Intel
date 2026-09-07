with open('templates/chat.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Line 7670 to 7695:")
for i in range(7669, 7695):
    print(f"{i+1}: {lines[i]}", end="")

print("\n\nLine 7765 to 7790 (Agent start):")
for i in range(7764, 7790):
    print(f"{i+1}: {lines[i]}", end="")

print("\n\nLine 9815 to 9832 (Style end):")
for i in range(9814, 9832):
    print(f"{i+1}: {lines[i]}", end="")

import re

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    text = f.read()

# Verify the unclosed tooltip rule at line 7677
pos_tooltip = text.find('[data-tooltip]:hover::after {')
assert pos_tooltip != -1, "tooltip rule not found"
print("Found tooltip at pos:", pos_tooltip)

# Let's inspect the exact lines around tooltip
lines = text.split('\n')
for idx, l in enumerate(lines):
    if '[data-tooltip]:hover::after {' in l:
        print(f"Tooltip at line {idx+1}")
        for j in range(max(0, idx-5), min(len(lines), idx+25)):
            print(f"{j+1}: {lines[j]}")
        break

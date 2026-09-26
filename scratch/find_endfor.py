import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    content = f.read()

pos_m = content.find('{% for m in messages %}')
pos_end = content.find('{% endfor %}', pos_m)
print("pos_m:", pos_m, "pos_end:", pos_end)
print(content[pos_end-50:pos_end+300])

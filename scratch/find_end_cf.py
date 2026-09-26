import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    content = f.read()

pos_cf = content.find('id="chat-flow"')
pos_composer = content.find('id="chat-composer-container"')
print("pos_cf:", pos_cf, "pos_composer:", pos_composer)
print("Between end of chat-flow and composer:")
print(content[pos_composer-400:pos_composer])

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    text = f.read()

pos_root = text.find(':root')
if pos_root != -1:
    pos_end = text.find('}', pos_root)
    print(text[pos_root:pos_end+1])

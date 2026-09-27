with open('templates/chat/scripts.html', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('window.recordSpokenTurn =')
print(text[idx:idx+2000])

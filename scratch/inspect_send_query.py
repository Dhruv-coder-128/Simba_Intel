with open('templates/chat/scripts.html', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('const sessionParam = new URLSearchParams(window.location.search).get("session");')
print(text[idx:idx+1500])

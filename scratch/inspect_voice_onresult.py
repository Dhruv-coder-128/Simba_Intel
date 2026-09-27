with open('templates/chat/scripts.html', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('voiceRecognition.onresult = function (event) {')
print(text[idx:idx+2500])

with open('templates/chat/scripts.html', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('if (typeof maybeVoiceSpeakResponse === \'function\') {')
print(text[max(0, idx-600):idx+1200])

with open('templates/chat/scripts.html', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('maybeVoiceSpeakResponse')
while idx != -1:
    print(f"Match at {idx}:")
    print(text[max(0, idx-100):min(len(text), idx+300)])
    print('==='*15)
    idx = text.find('maybeVoiceSpeakResponse', idx+1)

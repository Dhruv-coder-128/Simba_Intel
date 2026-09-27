with open('templates/chat/scripts.html', 'r', encoding='utf-8') as f:
    text = f.read()

idx = text.find('window.syncDesktopAgentStatus =')
end_idx = text.find('window.togglePcAgentModal =', idx)
print(text[idx:end_idx])

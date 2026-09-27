with open('templates/chat.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print('Total lines:', len(lines))

landmarks = [
    '<style>',
    '</style>',
    '<div id="sidebar">',
    '<div id="workspace">',
    '<div id="chat-flow">',
    "{% if session_type == 'agent' %}",
    "{% elif session_type == 'voice' %}",
    "{% else %}",
    '<div id="input-wrapper">',
    '<script>',
    '<div id="actionDiscoveryModal"',
    '<div id="pcAgentInstructionsModal"'
]

for lm in landmarks:
    for idx, line in enumerate(lines):
        if lm in line:
            print(f'{lm:35} at line {idx + 1}')

import re

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    text = f.read()

p1 = text.find('id="agentWorkspace"')
p2 = text.find('id="voiceWorkspace"')
p3 = text.find('id="agentTaskHistoryDrawer"')
p4 = text.find('id="actionDiscoveryModal"')
p5 = text.find('id="pcAgentInstructionsModal"')

blocks = {
    'Agent Workspace': text[p1:p2] if p1!=-1 and p2!=-1 else '',
    'Voice Workspace': text[p2:text.find('{% else %}', p2)] if p2!=-1 else '',
    'Task History Drawer': text[p3:p4] if p3!=-1 and p4!=-1 else '',
    'Discovery Modal': text[p4:p5] if p4!=-1 and p5!=-1 else '',
}

for name, blk in blocks.items():
    print(f'\n=== {name} ===')
    matches = re.findall(r'<([a-zA-Z0-9]+)([^>]*)>', blk)
    for tag, attrs in matches:
        if tag.lower() in ['button', 'input', 'select', 'textarea', 'details', 'summary']:
            cls = re.search(r'class=["\']([^"\']*)["\']', attrs)
            id_ = re.search(r'id=["\']([^"\']*)["\']', attrs)
            typ = re.search(r'type=["\']([^"\']*)["\']', attrs)
            c = cls.group(1) if cls else 'NO_CLASS'
            i = id_.group(1) if id_ else 'NO_ID'
            t = typ.group(1) if typ else 'NO_TYPE'
            print(f'<{tag} type="{t}" id="{i}" class="{c}">')

import re

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    text = f.read()

# Check elements inside agent and voice workspaces and drawers
snippets = {
    'Agent Workspace': re.search(r'<div class="agent-workspace-wrapper" id="agentWorkspace">([\s\S]*?)</div>\s*\{%\s*elif', text),
    'Voice Workspace': re.search(r'<div class="voice-workspace-wrapper" id="voiceWorkspace">([\s\S]*?)</div>\s*\{%\s*else', text),
    'Task History Drawer': re.search(r'<div id="agentTaskHistoryDrawer"[\s\S]*?</div>\s*</div>\s*</div>', text),
    'Action Discovery Modal': re.search(r'<div id="actionDiscoveryModal"[\s\S]*?</div>\s*</div>\s*</div>', text)
}

interactive_tags = ['button', 'select', 'input', 'details', 'summary']

for name, match in snippets.items():
    print(f"\n==================== {name} ====================")
    if not match:
        print("MATCH NOT FOUND")
        continue
    content = match.group(0)
    for tag in interactive_tags:
        found_elements = re.findall(r'<' + tag + r'([^>]*)>', content)
        for elem in found_elements:
            # extract class and id
            cls = re.search(r'class=[\"\'](.*?)[\"\']', elem)
            id_ = re.search(r'id=[\"\'](.*?)[\"\']', elem)
            c_val = cls.group(1) if cls else "NO CLASS!"
            i_val = id_.group(1) if id_ else ""
            print(f"<{tag}> class='{c_val}' id='{i_val}'")

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("=== AGENT WORKSPACE DOM (lines 10530 to 10835) ===")
with open('scratch/agent_workspace_dom.html', 'w', encoding='utf-8') as out:
    for i in range(10525, 10835):
        out.write(f"{i+1}: {lines[i]}")

print("Saved scratch/agent_workspace_dom.html")

print("=== VOICE WORKSPACE DOM (lines 10835 to 10937) ===")
with open('scratch/voice_workspace_dom.html', 'w', encoding='utf-8') as out:
    for i in range(10834, 10938):
        out.write(f"{i+1}: {lines[i]}")

print("Saved scratch/voice_workspace_dom.html")

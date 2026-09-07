import re

# Read current templates/chat.html
with open('templates/chat.html', 'r', encoding='utf-8') as f:
    chat_html = f.read()

# Locate the beginning of Agent Mode styles
agent_start_marker = "        /* ==========================================================================\n           AGENT MODE WORKSPACE (CYBERPUNK HUD ARCHITECTURE)\n           ========================================================================== */"
# Locate the end of the <style> tag
style_end_marker = "    </style>"

pos_agent_start = chat_html.find(agent_start_marker)
pos_style_end = chat_html.find(style_end_marker, pos_agent_start)

assert pos_agent_start != -1, "agent_start_marker not found"
assert pos_style_end != -1, "style_end_marker not found"
print(f"Found CSS replacement region: {pos_agent_start} to {pos_style_end}")

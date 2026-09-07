import sys, os
sys.path.insert(0, os.path.abspath('.'))
import re
from scratch.generate_agent_voice_css import css_block

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    text = f.read()

agent_start_marker = "        /* ==========================================================================\n           AGENT MODE WORKSPACE (CYBERPUNK HUD ARCHITECTURE)\n           ========================================================================== */"
style_end_marker = "    </style>"

pos_agent_start = text.find(agent_start_marker)
pos_style_end = text.find(style_end_marker, pos_agent_start)

assert pos_agent_start != -1, "agent_start_marker not found"
assert pos_style_end != -1, "style_end_marker not found"

new_html = text[:pos_agent_start] + css_block + text[pos_style_end + len(style_end_marker):]

# Validate entire <style> in new_html
pos_style_start = new_html.find('<style')
pos_style_close = new_html.find('</style>')

style_content = new_html[pos_style_start:pos_style_close]
clean = re.sub(r'/\*.*?\*/', '', style_content, flags=re.DOTALL)
clean = re.sub(r'"(?:\\.|[^"\\])*"', '', clean)
clean = re.sub(r"'(?:\\.|[^'\\])*'", '', clean)

o = clean.count('{')
c = clean.count('}')
print(f"Entire <style> tag - Open: {o}, Close: {c}, Diff: {o - c}")

if o == c:
    with open('templates/chat.html', 'w', encoding='utf-8') as f:
        f.write(new_html)
    print("Successfully updated templates/chat.html with new Agent/Voice CSS foundation!")
else:
    print(f"Error: Entire style tag is not balanced! Diff: {o - c}")

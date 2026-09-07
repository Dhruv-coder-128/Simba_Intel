import sys, os
sys.path.insert(0, os.path.abspath('.'))
import re
from scratch.generate_agent_voice_css import css_block

clean = re.sub(r'/\*.*?\*/', '', css_block, flags=re.DOTALL)
clean = re.sub(r'"(?:\\.|[^"\\])*"', '', clean)
clean = re.sub(r"'(?:\\.|[^'\\])*'", '', clean)

o = clean.count('{')
c = clean.count('}')
print(f"Open: {o}, Close: {c}, Diff: {o - c}")

if o != c:
    lines = clean.split('\n')
    balance = 0
    for idx, l in enumerate(lines):
        balance += (l.count('{') - l.count('}'))
        if balance < 0:
            print(f"Negative balance at line {idx+1}: {l}")
            break
    print(f"Final balance: {balance}")
else:
    print("CSS block is perfectly balanced (Diff = 0)!")

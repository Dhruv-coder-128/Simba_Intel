import sys
import re

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

print('=== MODE BUTTONS ===')
for m in re.findall(r'data-mode=["\'](.*?)["\']', text):
    print(m)

print('\n=== AGENT IDs ===')
for m in sorted(set(re.findall(r'id=["\']([^"\']*agent[^"\']*)["\']', text, re.I))):
    print(m)

print('\n=== VOICE IDs ===')
for m in sorted(set(re.findall(r'id=["\']([^"\']*voice[^"\']*)["\']', text, re.I))):
    print(m)

print('\n=== WORKSPACE / MODE WRAPPERS ===')
for m in re.findall(r'<div[^>]+id=["\']([^"\']*(?:workspace|mode|chat-flow|chat-container)[^"\']*)["\'][^>]*>', text, re.I):
    print(m)

import os
import sys

BASE_DIR = os.getcwd()
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings')
import django
django.setup()

from django.test import Client
from django.contrib.auth.models import User

client = Client()
user = User.objects.first()
client.force_login(user)

res_voice = client.get('/?type=voice')
print('Voice page status:', res_voice.status_code)
assert res_voice.status_code == 200
assert b'VOICE AGENT' in res_voice.content
assert b'id="voiceHeroStage"' in res_voice.content
assert b'id="input-wrapper"' not in res_voice.content

res_agent = client.get('/?type=agent')
print('Agent page status:', res_agent.status_code)
assert res_agent.status_code == 200
assert b'AGENT MODE' in res_agent.content

res_assist = client.get('/?type=assistant')
print('Assistant page status:', res_assist.status_code)
assert res_assist.status_code == 200
assert b'id="input-wrapper"' in res_assist.content

print('All 3 mode endpoints verified successfully with active user session!')

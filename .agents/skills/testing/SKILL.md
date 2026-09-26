---
name: testing
description: >-
  Procedures and standards for running and authoring automated tests in Simba Intel.
  Use when writing unit tests, running test suites, verifying bug fixes, mocking external
  AI APIs, testing message tree branching, or validating RBAC permissions.
---

# Simba Intel Testing Runbook

Follow these procedures for authoring and running automated tests in Simba Intel.

## 1. Running Tests

### Django System Check
Always run before executing tests:
```bash
python manage.py check
```

### Targeted Test Execution
Run the narrowest relevant test first to save time and compute:
```bash
# Specific test method:
python manage.py test chat.tests.ModelRegistryTests.test_get_model_config_returns_expected_provider

# Specific test class:
python manage.py test chat.tests.ModelRegistryTests

# Specific test module:
python manage.py test chat.test_rbac
python manage.py test chat.test_admin_console
python manage.py test chat.test_agent_desktop

# Full chat application test suite:
python manage.py test chat
```

## 2. Authoring New Tests

### Standard Test Boilerplate
```python
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from chat.models import ChatSession, Message, UserProfile, Role

User = get_user_model()

class CustomFeatureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword123"
        )
        self.profile = UserProfile.get_or_create_for(self.user)
        self.client.force_login(self.user)

    def test_authenticated_view_access(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
```

### Mocking External AI Providers
Always mock external API clients (`Groq`, `Mistral`, `Tavily`, `Resend`):
```python
@patch("chat.services.ai_router.get_provider")
def test_ai_streaming_response(self, mock_get_provider):
    mock_provider = MagicMock()
    mock_provider.chat_stream.return_value = iter(["Hello", " world", "!"])
    mock_get_provider.return_value = mock_provider

    session = ChatSession.objects.create(user=self.user, title="Test Chat")
    response = self.client.post(reverse("ask_ai"), {
        "query": "Hello",
        "session_id": session.id,
        "model": "cyber-max",
    })
    self.assertEqual(response.status_code, 200)
```

### Verifying Message Tree Writes
Verify that conversational turns append to `Message` and update `active_leaf`:
```python
def test_message_tree_integrity(self):
    session = ChatSession.objects.create(user=self.user, title="Tree Test")
    self.assertIsNone(session.active_leaf)

    from chat.services.message_tree import append_turn
    user_msg, assistant_msg = append_turn(session, "Hi", "Hello back")

    session.refresh_from_db()
    self.assertEqual(session.active_leaf, assistant_msg)
    self.assertEqual(assistant_msg.parent, user_msg)
    self.assertEqual(user_msg.role, "user")
    self.assertEqual(assistant_msg.role, "assistant")
```

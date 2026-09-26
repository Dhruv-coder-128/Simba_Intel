# Testing & Verification Rules

This rule outlines testing standards, verification workflows, and test execution for Simba Intel.

## Verification Policy

1. **Verification Ladder**:
   Always execute the smallest relevant check first before broader runs:
   ```
   Step 1: Syntax & Django System Check
           python manage.py check
   Step 2: Migration Consistency Check (if models modified)
           python manage.py makemigrations --dry-run
   Step 3: Targeted Unit / Module Test
           python manage.py test chat.tests.<SpecificTestClass>
   Step 4: Broader App Regression Test
           python manage.py test chat
   ```

2. **Truthful Verification**:
   - Never claim an implementation or bug fix works without running the corresponding verification commands.
   - If tests fail, report the exact error and trace root causes rather than hiding or ignoring test output.

## Test Suite Structure

The test suite is organized into modular files within `chat/`:

| Test Module | Coverage Scope |
| :--- | :--- |
| `chat.tests` | Core chat flows, message tree, model registry, AI providers, usage & rate limits, session management |
| `chat.test_rbac` | Role hierarchy (`OWNER` through `USER`), permissions, `@require_role` decorators |
| `chat.test_admin_console` | Super admin dashboard, user moderation, bans, audit logs, feature flags |
| `chat.test_admin_console_extras` | Live monitors, system health, reports, broadcasts |
| `chat.test_agent_cloud_connection` | Agent API endpoints (`/api/agent/*`), token auth, polling, heartbeats |
| `chat.test_agent_desktop` | Local desktop agent tools (window, mouse, keyboard, files, risk levels) |
| `chat.test_auth_upgrade` | Recovery codes, session revocation, profile settings |
| `chat.test_email` | Resend HTTPS email backend, template rendering, failure resilience |

## Authoring New Tests

1. **Mock External Providers**:
   - External APIs (Groq, Mistral, Tavily, Resend, OpenRouter) must **always** be mocked using `unittest.mock.patch` or `MagicMock`.
   - Never execute live network calls to third-party AI APIs during automated tests.

2. **Authentication in Tests**:
   - Use `self.client.force_login(user)` rather than manually passing session cookies.
   - Ensure test users have proper `UserProfile` instances attached via `UserProfile.get_or_create_for(user)`.

3. **Message Tree Assertions**:
   - When testing conversational writes, verify that:
     - `Message` records are created with proper `role` and `parent`.
     - `ChatSession.active_leaf` points to the newest assistant message.
     - `ChatMessage` row counts remain unchanged.

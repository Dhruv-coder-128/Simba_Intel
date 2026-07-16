import importlib
from unittest.mock import patch

from django.apps import apps as live_apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from chat.models import ChatMessage, ChatSession, Message, RecoveryCode, UsageEvent, UserProfile
from chat.providers.pollinations_image_provider import PollinationsImageProvider
from chat.services.cost_table import estimate_cost
from chat.services.memory import get_conversation_history
from chat.services.message_tree import append_turn, build_display_messages, walk_active_chain
from chat.services.model_registry import get_model_config, list_available_models
from chat.services.usage import RATE_LIMIT_MAX_REQUESTS, check_rate_limit, estimate_tokens, record_usage
from chat.services.verification import is_email_verified, verification_required

User = get_user_model()

_backfill_migration = importlib.import_module("chat.migrations.0010_backfill_message_tree")


class ModelRegistryTests(TestCase):
    def test_get_model_config_returns_expected_provider(self):
        config = get_model_config("cyber-max")
        self.assertEqual(config.provider, "groq")

    def test_get_model_config_is_case_insensitive(self):
        config = get_model_config("CYBER-MAX")
        self.assertEqual(config.display_name, "Cyber Max")

    def test_list_available_models_shape(self):
        models = list_available_models()
        self.assertTrue(all({"id", "display_name", "provider"} <= set(m) for m in models))


class PollinationsImageProviderTests(TestCase):
    def setUp(self):
        self.provider = PollinationsImageProvider()

    def test_invalid_aspect_ratio_defaults_to_square(self):
        result = self.provider.generate("a cat", aspect_ratio="not-a-ratio")
        self.assertTrue(result["success"])
        self.assertEqual((result["width"], result["height"]), (1024, 1024))

    def test_valid_aspect_ratio_maps_to_expected_size(self):
        result = self.provider.generate("a cat", aspect_ratio="16:9")
        self.assertEqual((result["width"], result["height"]), (1344, 768))

    def test_enhanced_prompt_not_returned_as_the_visible_prompt(self):
        result = self.provider.generate("a cat")
        self.assertEqual(result["prompt"], "a cat")
        self.assertNotEqual(result["enhanced_prompt"], "a cat")
        self.assertIn("a cat", result["enhanced_prompt"])

    def test_seed_is_embedded_in_generated_url(self):
        result = self.provider.generate("a cat", seed=42)
        self.assertIn("seed=42", result["image_url"])


class ConversationHistoryTests(TestCase):
    """get_conversation_history now reads the Message tree (via
    session.active_leaf), not the legacy ChatMessage table - fixtures here
    build the tree directly with append_turn, same as ask_ai does."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.session = ChatSession.objects.create(user=self.user, title="Test session")

    def test_text_turn_round_trips(self):
        append_turn(self.session, "hi", "hello")
        history = get_conversation_history(self.session)
        self.assertEqual(history, [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ])

    def test_image_turn_never_yields_empty_assistant_content(self):
        append_turn(
            self.session, "draw a cat", "",
            assistant_extra_data={"type": "image", "prompt": "draw a cat"},
        )
        history = get_conversation_history(self.session)
        assistant_turns = [m for m in history if m["role"] == "assistant"]
        self.assertEqual(len(assistant_turns), 1)
        self.assertTrue(assistant_turns[0]["content"].strip())

    def test_stray_empty_assistant_turn_is_skipped_not_sent_blank(self):
        append_turn(self.session, "hi", "")
        history = get_conversation_history(self.session)
        self.assertEqual(history, [{"role": "user", "content": "hi"}])
        for msg in history:
            self.assertNotEqual(msg, {"role": "assistant", "content": ""})

    def test_history_respects_turn_limit_from_oldest(self):
        for i in range(5):
            append_turn(self.session, f"q{i}", f"a{i}")
        history = get_conversation_history(self.session, limit=2)
        self.assertEqual(history, [
            {"role": "user", "content": "q0"},
            {"role": "assistant", "content": "a0"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ])

    def test_history_empty_for_session_with_no_active_leaf(self):
        self.assertEqual(get_conversation_history(self.session), [])


class AskAiViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")

    def test_chat_home_requires_login(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 302)

    def test_ask_ai_rejects_empty_query(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("ask_ai"), {"query": "   ", "model_id": "cyber-max"})
        self.assertEqual(response.status_code, 400)

    def test_ask_ai_requires_login(self):
        response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max"})
        self.assertEqual(response.status_code, 302)

    def test_system_stats_requires_login(self):
        response = self.client.get(reverse("system_stats"))
        self.assertEqual(response.status_code, 302)


class AttachmentTests(TestCase):
    """Phase 1: file upload -> chat context, and true vision for image attachments."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.client.force_login(self.user)

    def _consume(self, response):
        return b"".join(response.streaming_content).decode()

    @patch("chat.views.chat_stream")
    def test_text_attachment_is_folded_into_query_context(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["Hello"])
        txt_file = SimpleUploadedFile("notes.txt", b"Some extracted context", content_type="text/plain")
        response = self.client.post(reverse("ask_ai"), {
            "query": "Summarize this",
            "model_id": "cyber-max",
            "attachment": txt_file,
        })
        self.assertEqual(response.status_code, 200)
        self._consume(response)

        called_messages = mock_chat_stream.call_args[0][1]
        combined = " ".join(m["content"] for m in called_messages if isinstance(m["content"], str))
        self.assertIn("Some extracted context", combined)

    @patch("chat.views.ai_vision")
    def test_image_attachment_with_vision_model_calls_vision(self, mock_vision):
        mock_vision.return_value = "A red apple on a table."
        img = SimpleUploadedFile("photo.png", b"fake-image-bytes", content_type="image/png")
        response = self.client.post(reverse("ask_ai"), {
            "query": "What is this?",
            "model_id": "sky-net",  # mistral, supports_vision=True
            "attachment": img,
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "vision")
        self.assertEqual(data["response"], "A red apple on a table.")
        mock_vision.assert_called_once()

    @patch("chat.views.analyze_file")
    @patch("chat.views.chat_stream")
    def test_image_attachment_without_vision_support_falls_back_to_ocr(self, mock_chat_stream, mock_analyze):
        mock_analyze.return_value = "OCR extracted text"
        mock_chat_stream.return_value = iter(["ok"])
        img = SimpleUploadedFile("photo.png", b"fake-image-bytes", content_type="image/png")
        response = self.client.post(reverse("ask_ai"), {
            "query": "What does this say?",
            "model_id": "cyber-max",  # groq, supports_vision=False
            "attachment": img,
        })
        self.assertEqual(response.status_code, 200)
        self._consume(response)

        mock_analyze.assert_called_once()
        called_messages = mock_chat_stream.call_args[0][1]
        combined = " ".join(m["content"] for m in called_messages if isinstance(m["content"], str))
        self.assertIn("OCR extracted text", combined)

    def test_attachment_too_large_is_rejected(self):
        big_file = SimpleUploadedFile("big.txt", b"x" * (11 * 1024 * 1024), content_type="text/plain")
        response = self.client.post(reverse("ask_ai"), {
            "query": "hi",
            "model_id": "cyber-max",
            "attachment": big_file,
        })
        self.assertEqual(response.status_code, 400)

    def test_attachment_disallowed_extension_is_rejected(self):
        bad_file = SimpleUploadedFile("script.exe", b"binary", content_type="application/octet-stream")
        response = self.client.post(reverse("ask_ai"), {
            "query": "hi",
            "model_id": "cyber-max",
            "attachment": bad_file,
        })
        self.assertEqual(response.status_code, 400)

    @patch("chat.views.chat_stream")
    def test_empty_query_with_attachment_is_accepted(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["ok"])
        txt_file = SimpleUploadedFile("notes.txt", b"content", content_type="text/plain")
        response = self.client.post(reverse("ask_ai"), {
            "query": "",
            "model_id": "cyber-max",
            "attachment": txt_file,
        })
        self.assertEqual(response.status_code, 200)

    def test_empty_query_without_attachment_still_rejected(self):
        response = self.client.post(reverse("ask_ai"), {"query": "", "model_id": "cyber-max"})
        self.assertEqual(response.status_code, 400)

    @patch("chat.views.ai_vision")
    def test_multiple_images_are_all_sent_to_vision_model(self, mock_vision):
        mock_vision.return_value = "Two images: a cat and a dog."
        img1 = SimpleUploadedFile("cat.png", b"fake-cat-bytes", content_type="image/png")
        img2 = SimpleUploadedFile("dog.webp", b"fake-dog-bytes", content_type="image/webp")
        response = self.client.post(reverse("ask_ai"), {
            "query": "Compare these",
            "model_id": "sky-net",
            "attachment": [img1, img2],
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "vision")
        self.assertEqual(data["filenames"], ["cat.png", "dog.webp"])
        self.assertEqual(len(data["image_previews"]), 2)

        sent_messages = mock_vision.call_args[0][1]
        content = sent_messages[1]["content"]
        image_blocks = [c for c in content if c["type"] == "image_url"]
        self.assertEqual(len(image_blocks), 2)

    def test_too_many_attachments_rejected(self):
        files = [
            SimpleUploadedFile(f"img{i}.png", b"x", content_type="image/png")
            for i in range(8)
        ]
        response = self.client.post(reverse("ask_ai"), {
            "query": "hi",
            "model_id": "cyber-max",
            "attachment": files,
        })
        self.assertEqual(response.status_code, 400)

    @patch("chat.views.ai_vision")
    def test_webp_attachment_accepted_by_vision_model(self, mock_vision):
        mock_vision.return_value = "A photo."
        img = SimpleUploadedFile("photo.webp", b"fake-bytes", content_type="image/webp")
        response = self.client.post(reverse("ask_ai"), {
            "query": "What is this?",
            "model_id": "sky-net",
            "attachment": img,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["type"], "vision")


class UserProfileTests(TestCase):
    """Phase 2: per-user settings (theme, default model, toggles)."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.client.force_login(self.user)

    def test_profile_auto_created_on_chat_home(self):
        # Login itself now creates the profile (chat/signals.py records a
        # last-login IP/device/browser snapshot onto it), so by the time
        # setUp's force_login() has run, one already exists - this asserts
        # chat_home doesn't depend on the OLD lazy-creation-on-first-visit
        # path (i.e. it still works fine when a profile already exists).
        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())

    def test_settings_page_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("profile_settings"))
        self.assertEqual(response.status_code, 302)

    def test_settings_page_renders(self):
        response = self.client.get(reverse("profile_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SETTINGS")

    def test_settings_post_updates_profile(self):
        response = self.client.post(reverse("profile_settings"), {
            "display_name": "Dhruv S",
            "default_model": "sky-net",
            "theme": "matrix-green",
            "memory_enabled": "on",
        })
        self.assertEqual(response.status_code, 302)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.display_name, "Dhruv S")
        self.assertEqual(profile.default_model, "sky-net")
        self.assertEqual(profile.theme, "matrix-green")
        self.assertTrue(profile.memory_enabled)
        self.assertFalse(profile.notifications_enabled)  # unchecked checkbox

    def test_settings_post_rejects_invalid_model_and_theme(self):
        # update_or_create, not create: setUp's force_login already fired the
        # login signal, which creates the profile itself now (to record a
        # last-login snapshot on it).
        UserProfile.objects.update_or_create(user=self.user, defaults={"default_model": "cyber-max", "theme": "cyberpunk"})
        self.client.post(reverse("profile_settings"), {
            "display_name": "",
            "default_model": "not-a-real-model",
            "theme": "not-a-theme",
        })
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.default_model, "cyber-max")
        self.assertEqual(profile.theme, "cyberpunk")

    def test_chat_home_uses_profile_default_model(self):
        UserProfile.objects.update_or_create(user=self.user, defaults={"default_model": "sky-net"})
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["selected_model"], "sky-net")

    def test_session_selection_still_overrides_profile_default(self):
        UserProfile.objects.update_or_create(user=self.user, defaults={"default_model": "sky-net"})
        session = self.client.session
        session["selected_model"] = "nova-mind"
        session.save()
        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["selected_model"], "nova-mind")

    def test_theme_rendered_on_html_tag(self):
        UserProfile.objects.update_or_create(user=self.user, defaults={"theme": "midnight-purple"})
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'data-theme="midnight-purple"')


class MessageBackfillMigrationTests(TestCase):
    """Phase 3: the data migration that reproduces ChatMessage history as a
    Message tree. Tested directly against the real migration function -
    not a reimplementation - since this is the highest-risk part of the
    whole phase (it runs against real production chat history)."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.session = ChatSession.objects.create(user=self.user, title="Legacy session")

    def _run_backfill(self):
        _backfill_migration.backfill_messages(live_apps, None)

    def test_backfill_reproduces_linear_history_in_order(self):
        ChatMessage.objects.create(session=self.session, user_query="hi", ai_response="hello")
        ChatMessage.objects.create(session=self.session, user_query="how are you", ai_response="good")

        self._run_backfill()
        self.session.refresh_from_db()

        self.assertIsNotNone(self.session.active_leaf)
        self.assertEqual(self.session.active_leaf.role, "assistant")
        self.assertEqual(self.session.active_leaf.content, "good")

        chain = []
        node = self.session.active_leaf
        while node is not None:
            chain.append((node.role, node.content))
            node = node.parent
        chain.reverse()
        self.assertEqual(chain, [
            ("user", "hi"), ("assistant", "hello"),
            ("user", "how are you"), ("assistant", "good"),
        ])

    def test_backfill_is_idempotent_once_active_leaf_set(self):
        ChatMessage.objects.create(session=self.session, user_query="hi", ai_response="hello")
        self._run_backfill()
        count_after_first = Message.objects.filter(session=self.session).count()
        self._run_backfill()  # active_leaf is now set, should be a no-op
        count_after_second = Message.objects.filter(session=self.session).count()
        self.assertEqual(count_after_first, count_after_second)
        self.assertEqual(count_after_first, 2)

    def test_backfill_preserves_image_extra_data_empty_content_and_latency(self):
        ChatMessage.objects.create(
            session=self.session, user_query="draw a cat", ai_response="",
            extra_data={"type": "image", "image_url": "http://example.com/x.jpg"},
            latency=2.5,
        )
        self._run_backfill()
        self.session.refresh_from_db()
        leaf = self.session.active_leaf
        self.assertEqual(leaf.role, "assistant")
        self.assertEqual(leaf.content, "")
        self.assertEqual(leaf.extra_data["type"], "image")
        self.assertEqual(leaf.latency, 2.5)

    def test_backfill_skips_sessions_with_no_messages(self):
        empty_session = ChatSession.objects.create(user=self.user, title="Empty")
        self._run_backfill()
        empty_session.refresh_from_db()
        self.assertIsNone(empty_session.active_leaf)

    def test_backfill_does_not_touch_chatmessage_rows(self):
        ChatMessage.objects.create(session=self.session, user_query="hi", ai_response="hello")
        count_before = ChatMessage.objects.count()
        self._run_backfill()
        self.assertEqual(ChatMessage.objects.count(), count_before)
        # and the original row is unmodified
        cm = ChatMessage.objects.get(session=self.session)
        self.assertEqual(cm.user_query, "hi")
        self.assertEqual(cm.ai_response, "hello")

    def test_backfill_multiple_sessions_independently(self):
        session2 = ChatSession.objects.create(user=self.user, title="Second")
        ChatMessage.objects.create(session=self.session, user_query="a", ai_response="b")
        ChatMessage.objects.create(session=session2, user_query="c", ai_response="d")

        self._run_backfill()
        self.session.refresh_from_db()
        session2.refresh_from_db()

        self.assertEqual(self.session.active_leaf.content, "b")
        self.assertEqual(session2.active_leaf.content, "d")
        # No cross-session parent leakage
        self.assertEqual(self.session.active_leaf.parent.session_id, self.session.id)
        self.assertEqual(session2.active_leaf.parent.session_id, session2.id)


class MessageTreeWriteFlowTests(TestCase):
    """Phase 3: ask_ai now writes Message rows (not ChatMessage), and
    chat_home reads them back via build_display_messages. Covers the actual
    write paths, not just the tree helpers in isolation."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.client.force_login(self.user)

    def _consume(self, response):
        return b"".join(response.streaming_content).decode()

    @patch("chat.views.chat_stream")
    def test_text_send_writes_message_tree_not_chatmessage(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["Hello there"])
        response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max"})
        self.assertEqual(response.status_code, 200)
        self._consume(response)

        self.assertEqual(ChatMessage.objects.count(), 0)
        session = ChatSession.objects.get(user=self.user)
        self.assertIsNotNone(session.active_leaf)
        self.assertEqual(session.active_leaf.role, "assistant")
        self.assertEqual(session.active_leaf.content, "Hello there")
        self.assertEqual(session.active_leaf.parent.role, "user")
        self.assertEqual(session.active_leaf.parent.content, "hi")

    @patch("chat.views.chat_stream")
    def test_second_turn_chains_under_first(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["one"])
        r1 = self.client.post(reverse("ask_ai"), {"query": "first", "model_id": "cyber-max"})
        self._consume(r1)
        session_id = r1["X-Session-ID"]

        mock_chat_stream.return_value = iter(["two"])
        r2 = self.client.post(reverse("ask_ai"), {
            "query": "second", "model_id": "cyber-max", "session_id": session_id,
        })
        self._consume(r2)

        session = ChatSession.objects.get(id=session_id)
        self.assertEqual(Message.objects.filter(session=session).count(), 4)
        self.assertEqual(session.active_leaf.content, "two")
        self.assertEqual(session.active_leaf.parent.parent.parent.content, "first")

    def test_chat_home_renders_message_tree_history(self):
        session = ChatSession.objects.create(user=self.user, title="T")
        append_turn(session, "hi", "hello")
        response = self.client.get(reverse("home") + f"?session={session.id}")
        self.assertEqual(response.status_code, 200)
        messages = list(response.context["messages"])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].user_query, "hi")
        self.assertEqual(messages[0].ai_response, "hello")


class RegenerateEditEndpointTests(TestCase):
    """Phase 3: real sibling-branch semantics - regenerate/edit create a new
    sibling and move active_leaf, the old branch stays in the DB untouched."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.other_user = User.objects.create_user(username="mallory", password="testpass123")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user, title="T")
        self.user_msg, self.assistant_msg = append_turn(self.session, "hi", "hello")

    def _consume(self, response):
        return b"".join(response.streaming_content).decode()

    def test_session_active_leaf_returns_current_message_id(self):
        response = self.client.get(reverse("session_active_leaf", args=[self.session.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message_id"], self.assistant_msg.id)

    def test_session_active_leaf_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("session_active_leaf", args=[self.session.id]))
        self.assertEqual(response.status_code, 302)

    def test_session_active_leaf_blocks_other_users_session(self):
        other_session = ChatSession.objects.create(user=self.other_user, title="private")
        response = self.client.get(reverse("session_active_leaf", args=[other_session.id]))
        self.assertEqual(response.status_code, 404)

    @patch("chat.views.chat_stream")
    def test_regenerate_creates_sibling_and_preserves_old(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["a better answer"])
        response = self.client.post(
            reverse("regenerate_message", args=[self.assistant_msg.id]),
            {"model_id": "cyber-max"},
        )
        self.assertEqual(response.status_code, 200)
        self._consume(response)

        self.session.refresh_from_db()
        self.assistant_msg.refresh_from_db()

        # Old message untouched
        self.assertEqual(self.assistant_msg.content, "hello")
        # New sibling under the SAME parent
        self.assertNotEqual(self.session.active_leaf_id, self.assistant_msg.id)
        self.assertEqual(self.session.active_leaf.parent_id, self.assistant_msg.parent_id)
        self.assertEqual(self.session.active_leaf.content, "a better answer")
        # Both siblings still exist
        siblings = Message.objects.filter(parent=self.user_msg, role="assistant")
        self.assertEqual(siblings.count(), 2)

    def test_regenerate_requires_assistant_role(self):
        response = self.client.post(
            reverse("regenerate_message", args=[self.user_msg.id]), {"model_id": "cyber-max"}
        )
        self.assertEqual(response.status_code, 404)

    def test_regenerate_blocks_other_users_message(self):
        other_session = ChatSession.objects.create(user=self.other_user, title="private")
        _u, other_assistant = append_turn(other_session, "secret", "reply")
        response = self.client.post(
            reverse("regenerate_message", args=[other_assistant.id]), {"model_id": "cyber-max"}
        )
        self.assertEqual(response.status_code, 404)

    @patch("chat.views.chat_stream")
    def test_edit_creates_sibling_user_turn_and_fresh_reply(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["hi yourself"])
        response = self.client.post(
            reverse("edit_message", args=[self.user_msg.id]),
            {"content": "hi (edited)", "model_id": "cyber-max"},
        )
        self.assertEqual(response.status_code, 200)
        self._consume(response)

        self.session.refresh_from_db()
        self.user_msg.refresh_from_db()

        # Old user message and its old reply untouched
        self.assertEqual(self.user_msg.content, "hi")
        # New branch: sibling user node (same parent as the edited one) -> fresh assistant reply
        new_leaf = self.session.active_leaf
        self.assertEqual(new_leaf.role, "assistant")
        self.assertEqual(new_leaf.content, "hi yourself")
        new_user_node = new_leaf.parent
        self.assertEqual(new_user_node.content, "hi (edited)")
        self.assertEqual(new_user_node.parent_id, self.user_msg.parent_id)
        self.assertNotEqual(new_user_node.id, self.user_msg.id)

        # Old branch still fully in the DB
        siblings = Message.objects.filter(parent=self.user_msg.parent, role="user")
        self.assertEqual(siblings.count(), 2)

    def test_edit_rejects_empty_content(self):
        response = self.client.post(
            reverse("edit_message", args=[self.user_msg.id]), {"content": "   ", "model_id": "cyber-max"}
        )
        self.assertEqual(response.status_code, 400)

    def test_edit_requires_user_role(self):
        response = self.client.post(
            reverse("edit_message", args=[self.assistant_msg.id]),
            {"content": "new", "model_id": "cyber-max"},
        )
        self.assertEqual(response.status_code, 404)


class BranchSwitcherTests(TestCase):
    """New UI feature: navigate between sibling branches created by
    regenerate/edit, via build_display_messages' sibling metadata and the
    /messages/<id>/switch-branch/ endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.other_user = User.objects.create_user(username="mallory", password="testpass123")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user, title="T")
        self.user_msg, self.assistant_msg = append_turn(self.session, "hi", "hello")

    def _consume(self, response):
        return b"".join(response.streaming_content).decode()

    def test_single_reply_has_no_sibling_switcher_data(self):
        display = build_display_messages(self.session)
        self.assertEqual(len(display), 1)
        self.assertEqual(display[0].assistant_sibling_count, 1)
        self.assertEqual(display[0].user_sibling_count, 1)

    @patch("chat.views.chat_stream")
    def test_regenerate_produces_two_assistant_siblings_in_display(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["a better answer"])
        self._consume(self.client.post(
            reverse("regenerate_message", args=[self.assistant_msg.id]), {"model_id": "cyber-max"}
        ))
        self.session.refresh_from_db()
        display = build_display_messages(self.session)
        self.assertEqual(len(display), 1)
        self.assertEqual(display[0].assistant_sibling_count, 2)
        self.assertEqual(display[0].assistant_sibling_index, 2)
        self.assertEqual(len(display[0].assistant_sibling_ids), 2)

    @patch("chat.views.chat_stream")
    def test_edit_produces_two_user_siblings_in_display(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["hi yourself"])
        self._consume(self.client.post(
            reverse("edit_message", args=[self.user_msg.id]),
            {"content": "hi (edited)", "model_id": "cyber-max"},
        ))
        self.session.refresh_from_db()
        display = build_display_messages(self.session)
        self.assertEqual(len(display), 1)
        self.assertEqual(display[0].user_sibling_count, 2)
        self.assertEqual(display[0].user_sibling_index, 2)

    @patch("chat.views.chat_stream")
    def test_switch_branch_moves_active_leaf_to_old_assistant_sibling(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["a better answer"])
        self._consume(self.client.post(
            reverse("regenerate_message", args=[self.assistant_msg.id]), {"model_id": "cyber-max"}
        ))
        self.session.refresh_from_db()
        self.assertNotEqual(self.session.active_leaf_id, self.assistant_msg.id)

        response = self.client.post(reverse("switch_branch", args=[self.assistant_msg.id]))
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.active_leaf_id, self.assistant_msg.id)
        self.assertEqual(response.json()["message_id"], self.assistant_msg.id)

    @patch("chat.views.chat_stream")
    def test_switch_branch_on_user_message_moves_to_its_assistant_child(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["hi yourself"])
        self._consume(self.client.post(
            reverse("edit_message", args=[self.user_msg.id]),
            {"content": "hi (edited)", "model_id": "cyber-max"},
        ))
        self.session.refresh_from_db()
        new_leaf_id = self.session.active_leaf_id

        # Switch back to the ORIGINAL user turn - should land on its original assistant reply.
        response = self.client.post(reverse("switch_branch", args=[self.user_msg.id]))
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.active_leaf_id, self.assistant_msg.id)
        self.assertEqual(response.json()["user_message_id"], self.user_msg.id)
        self.assertNotEqual(self.session.active_leaf_id, new_leaf_id)

    def test_switch_branch_requires_login(self):
        self.client.logout()
        response = self.client.post(reverse("switch_branch", args=[self.assistant_msg.id]))
        self.assertEqual(response.status_code, 302)

    def test_switch_branch_blocks_other_users_message(self):
        other_session = ChatSession.objects.create(user=self.other_user, title="private")
        _u, other_assistant = append_turn(other_session, "secret", "reply")
        response = self.client.post(reverse("switch_branch", args=[other_assistant.id]))
        self.assertEqual(response.status_code, 404)

    def test_switch_branch_rejects_get(self):
        response = self.client.get(reverse("switch_branch", args=[self.assistant_msg.id]))
        self.assertEqual(response.status_code, 400)

    def test_siblings_endpoint_returns_single_sibling_before_regenerate(self):
        response = self.client.get(reverse("message_siblings", args=[self.assistant_msg.id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["sibling_ids"], [self.assistant_msg.id])
        self.assertEqual(data["role"], "assistant")

    @patch("chat.views.chat_stream")
    def test_siblings_endpoint_reflects_new_sibling_after_regenerate(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["a better answer"])
        self._consume(self.client.post(
            reverse("regenerate_message", args=[self.assistant_msg.id]), {"model_id": "cyber-max"}
        ))
        self.session.refresh_from_db()
        new_leaf_id = self.session.active_leaf_id
        response = self.client.get(reverse("message_siblings", args=[new_leaf_id]))
        data = response.json()
        self.assertEqual(len(data["sibling_ids"]), 2)
        self.assertIn(self.assistant_msg.id, data["sibling_ids"])
        self.assertEqual(data["current_id"], new_leaf_id)

    def test_siblings_endpoint_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("message_siblings", args=[self.assistant_msg.id]))
        self.assertEqual(response.status_code, 302)

    def test_siblings_endpoint_blocks_other_users_message(self):
        other_session = ChatSession.objects.create(user=self.other_user, title="private")
        _u, other_assistant = append_turn(other_session, "secret", "reply")
        response = self.client.get(reverse("message_siblings", args=[other_assistant.id]))
        self.assertEqual(response.status_code, 404)


class CostTableTests(TestCase):
    """Phase 4: cost estimation is a pure function of (model, tokens)."""

    def test_known_model_uses_its_rates(self):
        cost = estimate_cost("sky-net", prompt_tokens=1000, completion_tokens=1000)
        self.assertAlmostEqual(cost, 0.002 + 0.006)

    def test_flat_cost_model_ignores_token_counts(self):
        self.assertEqual(estimate_cost("image-studio", prompt_tokens=999999, completion_tokens=999999), 0.0)

    def test_unknown_model_defaults_to_zero(self):
        self.assertEqual(estimate_cost("some-future-model", prompt_tokens=500, completion_tokens=500), 0.0)


class UsageServiceTests(TestCase):
    """Phase 4: token estimation, usage recording, and rate limiting."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.session = ChatSession.objects.create(user=self.user, title="T")

    def test_estimate_tokens_heuristic(self):
        self.assertEqual(estimate_tokens("a" * 40), 10)
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("hi"), 1)  # floor of 1 for any non-empty text

    def test_record_usage_falls_back_to_estimate_when_no_captured_usage(self):
        event = record_usage(
            self.user, self.session, "groq", "cyber-max", "chat",
            prompt_text="a" * 40, completion_text="b" * 80,
            captured_usage={}, latency=1.2,
        )
        self.assertTrue(event.tokens_are_estimated)
        self.assertEqual(event.prompt_tokens, 10)
        self.assertEqual(event.completion_tokens, 20)

    def test_record_usage_prefers_real_captured_usage(self):
        event = record_usage(
            self.user, self.session, "mistral", "sky-net", "chat",
            prompt_text="a" * 40, completion_text="b" * 80,
            captured_usage={"prompt_tokens": 5, "completion_tokens": 26}, latency=1.2,
        )
        self.assertFalse(event.tokens_are_estimated)
        self.assertEqual(event.prompt_tokens, 5)
        self.assertEqual(event.completion_tokens, 26)

    def test_record_usage_computes_cost_from_cost_table(self):
        event = record_usage(
            self.user, self.session, "mistral", "sky-net", "chat",
            captured_usage={"prompt_tokens": 1000, "completion_tokens": 1000},
        )
        self.assertAlmostEqual(float(event.estimated_cost_usd), 0.008)

    def test_rate_limit_allows_under_cap(self):
        for _ in range(RATE_LIMIT_MAX_REQUESTS - 1):
            UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat")
        self.assertTrue(check_rate_limit(self.user))

    def test_rate_limit_blocks_at_cap(self):
        for _ in range(RATE_LIMIT_MAX_REQUESTS):
            UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat")
        self.assertFalse(check_rate_limit(self.user))

    def test_rate_limit_is_per_user(self):
        other = User.objects.create_user(username="mallory", password="testpass123")
        for _ in range(RATE_LIMIT_MAX_REQUESTS):
            UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat")
        self.assertTrue(check_rate_limit(other))


class UsageWiringTests(TestCase):
    """Phase 4: every successful AI call site writes exactly one UsageEvent,
    and rate limiting rejects requests once the cap is hit."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user, title="T")

    def _consume(self, response):
        return b"".join(response.streaming_content).decode()

    @patch("chat.views.chat_stream")
    def test_text_send_records_usage_event(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["hello there"])
        response = self.client.post(
            reverse("ask_ai"),
            {"query": "hi", "model_id": "cyber-max", "session_id": self.session.id},
        )
        self._consume(response)
        events = UsageEvent.objects.filter(user=self.user, event_type="chat")
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().provider, "groq")
        self.assertTrue(events.first().tokens_are_estimated)

    @patch("chat.views.chat_stream")
    def test_text_send_captures_real_usage_when_provider_supplies_it(self, mock_chat_stream):
        def fake_stream(model_id, messages, on_usage=None, **kwargs):
            if on_usage:
                on_usage({"prompt_tokens": 5, "completion_tokens": 26})
            return iter(["hello there"])
        mock_chat_stream.side_effect = fake_stream
        response = self.client.post(
            reverse("ask_ai"),
            {"query": "hi", "model_id": "sky-net", "session_id": self.session.id},
        )
        self._consume(response)
        event = UsageEvent.objects.filter(user=self.user, event_type="chat").first()
        self.assertFalse(event.tokens_are_estimated)
        self.assertEqual(event.prompt_tokens, 5)
        self.assertEqual(event.completion_tokens, 26)

    @patch("chat.views.generate_image")
    def test_image_generation_records_usage_event(self, mock_generate_image):
        mock_generate_image.return_value = {
            "success": True, "image_url": "http://example.com/a.png",
            "model_used": "Pollinations AI", "prompt": "a cat", "width": 1024, "height": 1024,
        }
        response = self.client.post(
            reverse("ask_ai"),
            {"query": "a cat", "model_id": "image-studio", "session_id": self.session.id},
        )
        self.assertEqual(response.status_code, 200)
        events = UsageEvent.objects.filter(user=self.user, event_type="image")
        self.assertEqual(events.count(), 1)
        self.assertEqual(float(events.first().estimated_cost_usd), 0.0)

    @patch("chat.views.ai_vision")
    def test_vision_call_records_usage_event(self, mock_vision):
        mock_vision.return_value = "A red apple."
        image = SimpleUploadedFile("apple.png", b"fake-bytes", content_type="image/png")
        response = self.client.post(
            reverse("ask_ai"),
            {"query": "what is this", "model_id": "sky-net", "session_id": self.session.id, "attachment": image},
        )
        self.assertEqual(response.status_code, 200)
        events = UsageEvent.objects.filter(user=self.user, event_type="vision")
        self.assertEqual(events.count(), 1)

    @patch("chat.views.chat_stream")
    def test_ask_ai_blocked_once_rate_limit_hit(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["ok"])
        for _ in range(RATE_LIMIT_MAX_REQUESTS):
            UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat")
        response = self.client.post(
            reverse("ask_ai"),
            {"query": "hi", "model_id": "cyber-max", "session_id": self.session.id},
        )
        self.assertEqual(response.status_code, 429)
        mock_chat_stream.assert_not_called()

    @patch("chat.views.chat_stream")
    def test_regenerate_records_usage_event(self, mock_chat_stream):
        user_msg, assistant_msg = append_turn(self.session, "hi", "hello")
        mock_chat_stream.return_value = iter(["a better answer"])
        response = self.client.post(
            reverse("regenerate_message", args=[assistant_msg.id]), {"model_id": "cyber-max"}
        )
        self._consume(response)
        self.assertEqual(UsageEvent.objects.filter(user=self.user, event_type="chat").count(), 1)

    @patch("chat.views.chat_stream")
    def test_edit_records_usage_event(self, mock_chat_stream):
        user_msg, assistant_msg = append_turn(self.session, "hi", "hello")
        mock_chat_stream.return_value = iter(["hi yourself"])
        response = self.client.post(
            reverse("edit_message", args=[user_msg.id]),
            {"content": "hi (edited)", "model_id": "cyber-max"},
        )
        self._consume(response)
        self.assertEqual(UsageEvent.objects.filter(user=self.user, event_type="chat").count(), 1)


class AnalyticsDashboardTests(TestCase):
    """Phase 5: analytics is a pure read-side view over UsageEvent."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.other_user = User.objects.create_user(username="mallory", password="testpass123")
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_renders_empty_state_with_no_usage(self):
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_requests"], 0)
        self.assertContains(response, "No usage recorded yet")

    def test_aggregates_totals_and_per_model_breakdown(self):
        UsageEvent.objects.create(
            user=self.user, provider="groq", model_id="cyber-max", event_type="chat",
            prompt_tokens=10, completion_tokens=20, estimated_cost_usd="0.001000", latency=1.0,
        )
        UsageEvent.objects.create(
            user=self.user, provider="mistral", model_id="sky-net", event_type="chat",
            prompt_tokens=5, completion_tokens=26, estimated_cost_usd="0.008000", latency=2.0,
        )
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_requests"], 2)
        self.assertEqual(response.context["total_tokens"], 61)
        self.assertAlmostEqual(response.context["total_cost"], 0.009)
        by_model = {row["model_id"]: row for row in response.context["by_model"]}
        self.assertEqual(by_model["cyber-max"]["requests"], 1)
        self.assertEqual(by_model["sky-net"]["tokens"], 31)

    def test_only_shows_current_users_events(self):
        UsageEvent.objects.create(
            user=self.other_user, provider="groq", model_id="cyber-max", event_type="chat",
            prompt_tokens=10, completion_tokens=20,
        )
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertEqual(response.context["total_requests"], 0)

    def test_estimated_footnote_shown_only_when_estimates_present(self):
        UsageEvent.objects.create(
            user=self.user, provider="mistral", model_id="sky-net", event_type="chat",
            prompt_tokens=5, completion_tokens=26, tokens_are_estimated=False,
        )
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertFalse(response.context["has_estimated_tokens"])

        UsageEvent.objects.create(
            user=self.user, provider="groq", model_id="cyber-max", event_type="chat",
            prompt_tokens=10, completion_tokens=20, tokens_are_estimated=True,
        )
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertTrue(response.context["has_estimated_tokens"])


class RecoveryCodeModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123", email="dhruv@example.com")

    def test_generated_code_matches_expected_format(self):
        _obj, raw = RecoveryCode.generate_for(self.user)
        self.assertRegex(raw, r"^SIMBA-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")

    def test_raw_code_verifies_against_stored_hash(self):
        obj, raw = RecoveryCode.generate_for(self.user)
        self.assertTrue(obj.verify(raw))

    def test_wrong_code_does_not_verify(self):
        obj, _raw = RecoveryCode.generate_for(self.user)
        self.assertFalse(obj.verify("SIMBA-0000-0000-0000"))

    def test_code_hash_never_contains_the_raw_code(self):
        obj, raw = RecoveryCode.generate_for(self.user)
        self.assertNotIn(raw, obj.code_hash)

    def test_generating_a_new_code_invalidates_the_previous_one(self):
        first_obj, first_raw = RecoveryCode.generate_for(self.user)
        second_obj, second_raw = RecoveryCode.generate_for(self.user)
        first_obj.refresh_from_db()
        self.assertFalse(first_obj.verify(first_raw))
        self.assertTrue(first_obj.verify(second_raw))  # same row, overwritten in place
        self.assertEqual(first_obj.id, second_obj.id)


class RecoveryCodePasswordResetFlowTests(TestCase):
    """Forgot Password -> Recovery Code -> New Password -> New Recovery Code."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="OldPass123!", email="dhruv@example.com")
        self.recovery_code, self.raw_code = RecoveryCode.generate_for(self.user)

    def test_forgot_password_accepts_username_or_email(self):
        r1 = self.client.post(reverse("forgot_password"), {"identifier": "dhruv"})
        self.assertRedirects(r1, reverse("verify_recovery_code"))
        self.client.session.flush()
        r2 = self.client.post(reverse("forgot_password"), {"identifier": "dhruv@example.com"})
        self.assertRedirects(r2, reverse("verify_recovery_code"))

    def test_forgot_password_does_not_leak_whether_account_exists(self):
        response = self.client.post(reverse("forgot_password"), {"identifier": "nobody"})
        # Same immediate redirect target either way - the endpoint must not
        # reveal account existence or whether it's eligible for recovery
        # codes (e.g. a Google-only account).
        self.assertRedirects(response, reverse("verify_recovery_code"), fetch_redirect_response=False)

    def test_google_only_account_is_not_recovery_eligible(self):
        google_user = User.objects.create_user(username="googleuser", email="googleuser@example.com")
        google_user.set_unusable_password()
        google_user.save()
        response = self.client.post(reverse("forgot_password"), {"identifier": "googleuser"})
        self.assertRedirects(response, reverse("verify_recovery_code"), fetch_redirect_response=False)
        # No session state was set for this account, so any code entered
        # next is rejected exactly like a nonexistent account would be.
        verify_response = self.client.post(reverse("verify_recovery_code"), {"code": "SIMBA-0000-0000-0000"})
        self.assertContains(verify_response, "invalid")

    def test_full_flow_reset_password_and_login_with_new_password(self):
        self.client.post(reverse("forgot_password"), {"identifier": "dhruv"})

        verify_response = self.client.post(reverse("verify_recovery_code"), {"code": self.raw_code})
        self.assertRedirects(verify_response, reverse("reset_password_recovery"))

        reset_response = self.client.post(reverse("reset_password_recovery"), {
            "password1": "BrandNewPass456!", "password2": "BrandNewPass456!",
        })
        self.assertRedirects(reset_response, reverse("recovery_code_display"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNewPass456!"))

        login_ok = self.client.login(username="dhruv", password="BrandNewPass456!")
        self.assertTrue(login_ok)

    def test_wrong_code_is_rejected(self):
        self.client.post(reverse("forgot_password"), {"identifier": "dhruv"})
        response = self.client.post(reverse("verify_recovery_code"), {"code": "SIMBA-0000-0000-0000"})
        self.assertContains(response, "invalid")

    def test_reset_generates_a_new_code_that_replaces_the_old_one(self):
        self.client.post(reverse("forgot_password"), {"identifier": "dhruv"})
        self.client.post(reverse("verify_recovery_code"), {"code": self.raw_code})
        self.client.post(reverse("reset_password_recovery"), {
            "password1": "BrandNewPass456!", "password2": "BrandNewPass456!",
        })
        self.recovery_code.refresh_from_db()
        self.assertFalse(self.recovery_code.verify(self.raw_code))

        display_response = self.client.get(reverse("recovery_code_display"))
        self.assertContains(display_response, "SIMBA-")

        # The one-time page can't be replayed - a second GET (session key
        # already popped) bounces away without showing anything. Not
        # following the redirect here: this client is anonymous at this
        # point in the flow, so "home" itself redirects again to login -
        # a separate, unrelated concern from what this test is checking.
        second_view = self.client.get(reverse("recovery_code_display"))
        self.assertRedirects(second_view, reverse("home"), fetch_redirect_response=False)

    def test_reset_password_rejects_mismatched_passwords(self):
        self.client.post(reverse("forgot_password"), {"identifier": "dhruv"})
        self.client.post(reverse("verify_recovery_code"), {"code": self.raw_code})
        response = self.client.post(reverse("reset_password_recovery"), {
            "password1": "BrandNewPass456!", "password2": "SomethingElse789!",
        })
        self.assertContains(response, "Those passwords don")  # avoids the apostrophe, HTML-escaped in the response
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldPass123!"))

    def test_cannot_reset_password_without_verifying_first(self):
        response = self.client.get(reverse("reset_password_recovery"))
        self.assertRedirects(response, reverse("forgot_password"))


class EmailVerificationGatingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123", email="dhruv@example.com")
        self.client.force_login(self.user)

    def test_verification_not_required_by_default(self):
        self.assertFalse(verification_required())
        self.assertTrue(is_email_verified(self.user))

    @override_settings(ACCOUNT_EMAIL_VERIFICATION="optional")
    def test_verification_required_when_optional_mode_enabled(self):
        self.assertTrue(verification_required())
        self.assertFalse(is_email_verified(self.user))

    @override_settings(ACCOUNT_EMAIL_VERIFICATION="optional")
    def test_verified_email_address_passes_gate(self):
        from allauth.account.models import EmailAddress
        EmailAddress.objects.create(user=self.user, email=self.user.email, verified=True, primary=True)
        self.assertTrue(is_email_verified(self.user))

    @override_settings(ACCOUNT_EMAIL_VERIFICATION="optional")
    def test_image_generation_blocked_for_unverified_user(self):
        response = self.client.post(reverse("ask_ai"), {"query": "a cat", "model_id": "image-studio"})
        data = response.json()
        self.assertEqual(data.get("type"), "error")
        self.assertTrue(data.get("requires_verification"))

    @override_settings(ACCOUNT_EMAIL_VERIFICATION="optional")
    def test_settings_save_blocked_for_unverified_user(self):
        response = self.client.post(reverse("profile_settings"), {"display_name": "Should Not Save"})
        self.assertEqual(response.status_code, 403)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.display_name, "")

    def test_settings_save_works_normally_when_verification_not_required(self):
        response = self.client.post(reverse("profile_settings"), {"display_name": "Saved Fine"})
        self.assertEqual(response.status_code, 302)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.display_name, "Saved Fine")

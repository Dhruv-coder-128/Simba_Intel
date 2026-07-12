from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from chat.models import ChatMessage, ChatSession
from chat.providers.pollinations_image_provider import PollinationsImageProvider
from chat.services.memory import get_conversation_history
from chat.services.model_registry import get_model_config, list_available_models

User = get_user_model()


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
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.session = ChatSession.objects.create(user=self.user, title="Test session")

    def test_text_turn_round_trips(self):
        ChatMessage.objects.create(session=self.session, user_query="hi", ai_response="hello")
        history = get_conversation_history(self.session)
        self.assertEqual(history, [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ])

    def test_image_turn_never_yields_empty_assistant_content(self):
        ChatMessage.objects.create(
            session=self.session,
            user_query="draw a cat",
            ai_response="",
            extra_data={"type": "image", "prompt": "draw a cat"},
        )
        history = get_conversation_history(self.session)
        assistant_turns = [m for m in history if m["role"] == "assistant"]
        self.assertEqual(len(assistant_turns), 1)
        self.assertTrue(assistant_turns[0]["content"].strip())

    def test_stray_empty_assistant_turn_is_skipped_not_sent_blank(self):
        ChatMessage.objects.create(session=self.session, user_query="hi", ai_response="")
        history = get_conversation_history(self.session)
        for msg in history:
            self.assertNotEqual(msg, {"role": "assistant", "content": ""})


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

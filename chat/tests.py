import importlib
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.apps import apps as live_apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from chat.models import ChatMessage, ChatSession, ErrorLog, FeatureFlag, Folder, Message, RecoveryCode, Role, SavedPrompt, UsageEvent, UserFact, UserProfile, UserSession
from chat.providers.pollinations_image_provider import PollinationsImageProvider
from chat.services.cost_table import estimate_cost
from chat.services.memory import get_conversation_history
from chat.services.message_tree import append_turn, build_display_messages, regenerate_assistant_reply, walk_active_chain
from chat.services.model_registry import MODEL_REGISTRY, ModelConfig, get_model_config, is_model_allowed_for_user, list_available_models
from chat.services.usage import RATE_LIMIT_MAX_REQUESTS, check_rate_limit, estimate_tokens, record_usage
from chat.services.verification import is_email_verified, verification_required

User = get_user_model()

_backfill_migration = importlib.import_module("chat.migrations.0010_backfill_message_tree")


class ModelRegistryTests(TestCase):
    def test_get_model_config_returns_expected_provider(self):
        # Sprint 6: Cyber Max became a virtual model backed by a pool of
        # real Groq models (chat/providers/virtual_provider.py) - "virtual"
        # is the correct provider now, not "groq" directly. See
        # VirtualRouterProviderTests for the routing/health/retry behavior
        # this enables.
        config = get_model_config("cyber-max")
        self.assertEqual(config.provider, "virtual")

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


class GroqProviderTests(TestCase):
    """Regression coverage for chat_stream's empty-choices handling (Sprint
    4 production-stability fix)."""

    def test_chat_stream_skips_chunks_with_empty_choices(self):
        from chat.providers.groq_provider import GroqProvider

        class FakeDelta:
            def __init__(self, content):
                self.content = content

        class FakeChoice:
            def __init__(self, content):
                self.delta = FakeDelta(content)

        class FakeChunk:
            def __init__(self, choices):
                self.choices = choices

        # A trailing keep-alive/usage-only chunk with an empty choices list
        # is a real, encountered shape (see MistralProvider.chat_stream,
        # which already guards against exactly this via stream_options) -
        # indexing choices[0] unconditionally would raise IndexError here
        # instead of just skipping the empty chunk.
        fake_stream = [
            FakeChunk([FakeChoice("Hello")]),
            FakeChunk([]),
            FakeChunk([FakeChoice(" world")]),
        ]

        provider = GroqProvider(api_key="test-key")
        with patch.object(provider.client.chat.completions, "create", return_value=fake_stream):
            tokens = list(provider.chat_stream([{"role": "user", "content": "hi"}], "cyber-max"))
        self.assertEqual(tokens, ["Hello", " world"])

    def test_vision_accepts_on_usage_without_forwarding_it_to_the_sdk_call(self):
        """Regression test for the same class of bug fixed in
        chat/providers/nvidia_vision_provider.py: chat/views.py's ask_ai
        always calls vision(..., on_usage=...) - without an explicit
        on_usage parameter here, it would fall into **kwargs and crash
        chat.completions.create() with "unexpected keyword argument"."""
        from chat.providers.groq_provider import GroqProvider

        received_kwargs = {}

        def create(model, messages, **kwargs):
            received_kwargs.update(kwargs)
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="a cat"))]
            return response

        provider = GroqProvider(api_key="test-key")
        with patch.object(provider.client.chat.completions, "create", side_effect=create) as mock_create:
            result = provider.vision(
                [{"role": "user", "content": "what is this?"}], "some-vision-model", on_usage=lambda u: None,
            )
            mock_create.assert_called_once()
        self.assertEqual(result, "a cat")
        self.assertNotIn("on_usage", received_kwargs)


class _RateLimitError(Exception):
    """Stands in for groq.RateLimitError - virtual_provider._is_rate_limit_error
    matches by exception class name, so a same-named local class exercises
    the exact same branch without importing the real SDK exception."""


class VirtualRouterProviderTests(TestCase):
    """Sprint 6: Cyber Max is now a virtual model backed by a pool of real
    Groq models (chat/providers/virtual_provider.py) - these are the
    scenarios the sprint explicitly asked to be verified: model 1 success
    (model 2+ never called), model 1 rate-limited (model 2 answers), model
    1 & 2 rate-limited (model 3 answers), and every model failing (a
    graceful exception, not an infinite loop). Also covers the health
    cooldown (a rate-limited model is skipped on the very next request, not
    just within the same one) and the retry-once-per-model rule for
    transient (non-rate-limit) failures.

    Patches chat.providers.virtual_provider.get_provider directly (the name
    bound inside that module) - VirtualRouterProvider.chat_stream calls
    get_provider(member.provider) once per pool member per attempt, so the
    mock's side_effect receives the real (messages, model, **kwargs) call
    exactly as a real GroqProvider would."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        from chat.providers.virtual_provider import MODEL_POOLS
        pool = sorted(MODEL_POOLS["cyber-max-pool"], key=lambda m: m.priority)
        self.m1, self.m2, self.m3 = pool[0].model, pool[1].model, pool[2].model
        self.messages = [{"role": "user", "content": "hi"}]

    def _router(self):
        from chat.providers.virtual_provider import VirtualRouterProvider
        return VirtualRouterProvider()

    def test_model1_success_model2_never_called(self):
        calls = []

        def fake(msgs, model, **kwargs):
            calls.append(model)
            if model == self.m1:
                return iter(["hello"])
            raise AssertionError(f"model2+ should never be called, got {model}")

        with patch("chat.providers.virtual_provider.get_provider") as mock_gp:
            mock_gp.return_value.chat_stream.side_effect = fake
            out = list(self._router().chat_stream(self.messages, "cyber-max-pool"))
        self.assertEqual(out, ["hello"])
        self.assertEqual(calls, [self.m1])

    def test_model1_rate_limited_model2_answers(self):
        calls = []

        def fake(msgs, model, **kwargs):
            calls.append(model)
            if model == self.m1:
                raise _RateLimitError("rate_limit_exceeded")
            if model == self.m2:
                return iter(["from model 2"])
            raise AssertionError(f"model3+ should never be called, got {model}")

        with patch("chat.providers.virtual_provider.get_provider") as mock_gp:
            mock_gp.return_value.chat_stream.side_effect = fake
            out = list(self._router().chat_stream(self.messages, "cyber-max-pool"))
        self.assertEqual(out, ["from model 2"])
        # A rate-limited model is never retried within the same request -
        # straight to cooldown and the next candidate.
        self.assertEqual(calls, [self.m1, self.m2])

    def test_model1_and_model2_rate_limited_model3_answers(self):
        def fake(msgs, model, **kwargs):
            if model in (self.m1, self.m2):
                raise _RateLimitError("rate_limit_exceeded")
            if model == self.m3:
                return iter(["from model 3"])
            raise AssertionError(f"model4+ should never be called, got {model}")

        with patch("chat.providers.virtual_provider.get_provider") as mock_gp:
            mock_gp.return_value.chat_stream.side_effect = fake
            out = list(self._router().chat_stream(self.messages, "cyber-max-pool"))
        self.assertEqual(out, ["from model 3"])

    def test_every_model_failing_raises_gracefully_not_infinitely(self):
        with patch("chat.providers.virtual_provider.get_provider") as mock_gp:
            mock_gp.return_value.chat_stream.side_effect = RuntimeError("total outage")
            with self.assertRaises(RuntimeError):
                list(self._router().chat_stream(self.messages, "cyber-max-pool"))

    def test_rate_limited_model_is_skipped_on_the_next_request(self):
        def fake(msgs, model, **kwargs):
            if model == self.m1:
                raise _RateLimitError("rate_limit_exceeded")
            return iter(["ok"])

        with patch("chat.providers.virtual_provider.get_provider") as mock_gp:
            mock_gp.return_value.chat_stream.side_effect = fake
            router = self._router()
            list(router.chat_stream(self.messages, "cyber-max-pool"))  # m1 fails, m2 answers

            calls = []

            def fake2(msgs, model, **kwargs):
                calls.append(model)
                return iter(["ok"])

            mock_gp.return_value.chat_stream.side_effect = fake2
            list(router.chat_stream(self.messages, "cyber-max-pool"))  # m1 should be skipped now
        self.assertNotIn(self.m1, calls)
        self.assertEqual(calls[0], self.m2)

    def test_transient_error_retried_once_then_moves_to_next_model(self):
        attempts_on_m1 = []

        def fake(msgs, model, **kwargs):
            if model == self.m1:
                attempts_on_m1.append(1)
                raise TimeoutError("connection timed out")
            if model == self.m2:
                return iter(["ok"])
            raise AssertionError(f"unexpected model {model}")

        with patch("chat.providers.virtual_provider.get_provider") as mock_gp:
            mock_gp.return_value.chat_stream.side_effect = fake
            out = list(self._router().chat_stream(self.messages, "cyber-max-pool"))
        self.assertEqual(out, ["ok"])
        # Exactly one retry (2 total attempts) before moving on.
        self.assertEqual(len(attempts_on_m1), 2)

    def test_transient_error_does_not_trigger_a_cooldown(self):
        with patch("chat.providers.virtual_provider.get_provider") as mock_gp:
            def fake(msgs, model, **kwargs):
                if model == self.m1:
                    raise TimeoutError("connection timed out")
                return iter(["ok"])
            mock_gp.return_value.chat_stream.side_effect = fake
            router = self._router()
            list(router.chat_stream(self.messages, "cyber-max-pool"))

            calls = []

            def fake2(msgs, model, **kwargs):
                calls.append(model)
                return iter(["ok"])

            mock_gp.return_value.chat_stream.side_effect = fake2
            list(router.chat_stream(self.messages, "cyber-max-pool"))
        # Unlike a rate limit, a timeout must not be remembered - model 1
        # is tried again (and succeeds) on the very next request.
        self.assertEqual(calls[0], self.m1)

    def test_end_to_end_through_ask_ai_stays_invisible_to_the_user(self):
        """Cyber Max's pool switching must never surface to the client - the
        streamed body should contain only the real answer, never a model
        name, provider name, or "switched" notice (that notice is reserved
        for the outer, cross-visible-model failover in ai_router.py, which
        this inner pool is designed to normally avoid ever triggering)."""
        user = User.objects.create_user(username="virtual_router_user", password="x")
        self.client.force_login(user)

        def fake(msgs, model, **kwargs):
            if model == self.m1:
                raise _RateLimitError("rate_limit_exceeded")
            return iter(["real answer"])

        with patch("chat.providers.virtual_provider.get_provider") as mock_gp, \
             patch("chat.services.conversation_intelligence.ai_chat") as mock_title_chat:
            mock_gp.return_value.chat_stream.side_effect = fake
            mock_title_chat.return_value = "Some Title"
            response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max"})
            body = b"".join(response.streaming_content).decode()

        self.assertEqual(body, "real answer")
        self.assertNotIn("Switched to", body)
        for leaked in (self.m1, self.m2, self.m3, "groq", "virtual"):
            self.assertNotIn(leaked, body)


def _fake_stream_chunk(content):
    """A minimal stand-in for an OpenAI streaming ChatCompletionChunk -
    just enough shape (.choices[0].delta.content) for
    nvidia_text_provider.py's _iter_stream() to read."""
    chunk = MagicMock()
    chunk.choices = [MagicMock(delta=MagicMock(content=content))]
    return chunk


def _fake_response(content):
    """A minimal stand-in for a non-streaming OpenAI ChatCompletion -
    just enough shape (.choices[0].message.content)."""
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


class NvidiaTextProviderTests(TestCase):
    """End-to-end coverage for chat/providers/nvidia_text_provider.py's
    fixed TEXT_MODELS priority chain - every failover trigger the spec
    calls out explicitly (404/429/500/503/timeout/connection/malformed -
    ANY error), with immediate, single-attempt, no-retry, no-memory
    failover: a model that fails is skipped for the rest of THIS request
    only, and is tried again fresh on the very next request. The
    `openai.OpenAI` client is replaced with a MagicMock after
    construction, so these never need a real NVIDIA_API_KEY or network
    access."""

    def _provider(self):
        from chat.providers.nvidia_text_provider import NvidiaTextProvider
        provider = NvidiaTextProvider(api_key="test-key")
        provider.client = MagicMock()
        return provider

    def test_fixed_model_list_contains_exactly_the_approved_models(self):
        """Membership only, not exact order - the priority order itself is
        a product decision that gets tuned independently of this test
        (see test_primary_model_answers_and_fallbacks_are_never_called for
        the order-sensitive behavior: whichever model is TEXT_MODELS[0] is
        always tried first). This test's job is narrower: catch an
        accidental addition, removal, or wrong id, not police ordering."""
        from chat.providers.nvidia_text_provider import TEXT_MODELS
        self.assertEqual(set(TEXT_MODELS), {
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "nvidia/nemotron-3-super-120b-a12b",
            "mistralai/mistral-nemotron",
            "meta/llama-3.1-70b-instruct",
        })
        self.assertEqual(len(TEXT_MODELS), 5, "no duplicate entries")

    def test_primary_model_answers_and_fallbacks_are_never_called(self):
        from chat.providers.nvidia_text_provider import TEXT_MODELS
        provider = self._provider()

        def create(model, messages, stream=False, **kwargs):
            if model == TEXT_MODELS[0]:
                return iter([_fake_stream_chunk("hello")])
            raise AssertionError(f"fallback model {model} should never be called when the primary succeeds")

        provider.client.chat.completions.create.side_effect = create
        out = list(provider.chat_stream([{"role": "user", "content": "hi"}], "quantum-core-pool"))
        self.assertEqual(out, ["hello"])

    def test_every_error_type_triggers_immediate_failover_with_a_single_attempt(self):
        from chat.providers.nvidia_text_provider import TEXT_MODELS

        class NotFoundError(Exception):
            status_code = 404

        class RateLimitError(Exception):
            status_code = 429

        class InternalServerError(Exception):
            status_code = 500

        class ServiceUnavailableError(Exception):
            status_code = 503

        class APITimeoutError(Exception):
            pass

        class APIConnectionError(Exception):
            pass

        error_types = [
            NotFoundError, RateLimitError, InternalServerError,
            ServiceUnavailableError, APITimeoutError, APIConnectionError,
        ]
        for error_cls in error_types:
            with self.subTest(error=error_cls.__name__):
                provider = self._provider()
                attempts = []

                def create(model, messages, stream=False, **kwargs):
                    attempts.append(model)
                    if model == TEXT_MODELS[0]:
                        raise error_cls("simulated failure")
                    return iter([_fake_stream_chunk("recovered")])

                provider.client.chat.completions.create.side_effect = create
                out = list(provider.chat_stream([{"role": "user", "content": "hi"}], "quantum-core-pool"))
                self.assertEqual(out, ["recovered"])
                self.assertEqual(attempts.count(TEXT_MODELS[0]), 1, "a failed model must never be retried")

    def test_malformed_response_triggers_immediate_failover(self):
        from chat.providers.nvidia_text_provider import TEXT_MODELS
        provider = self._provider()

        def malformed_stream():
            raise AttributeError("'NoneType' object has no attribute 'choices'")
            yield  # pragma: no cover

        def create(model, messages, stream=False, **kwargs):
            if model == TEXT_MODELS[0]:
                return malformed_stream()
            return iter([_fake_stream_chunk("recovered")])

        provider.client.chat.completions.create.side_effect = create
        out = list(provider.chat_stream([{"role": "user", "content": "hi"}], "quantum-core-pool"))
        self.assertEqual(out, ["recovered"])

    def test_every_model_exhausted_raises_without_leaking_the_provider_error(self):
        provider = self._provider()
        provider.client.chat.completions.create.side_effect = RuntimeError(
            "some internal NVIDIA endpoint detail"
        )
        with self.assertRaises(Exception) as ctx:
            list(provider.chat_stream([{"role": "user", "content": "hi"}], "quantum-core-pool"))
        # The real exception propagates internally (for logging), but no
        # caller-facing wrapping ever happens at this layer - the view
        # layer (chat/views.py) is what turns this into the generic safe
        # message shown to users, exactly as it already does for every
        # other provider's exhaustion.
        self.assertIsInstance(ctx.exception, RuntimeError)

    def test_no_memory_of_a_failed_model_across_separate_requests(self):
        """No blacklist cache, no health cache - a model that failed on
        one request is tried again, fresh, on the very next one."""
        from chat.providers.nvidia_text_provider import TEXT_MODELS
        provider = self._provider()
        attempts = []

        def always_fail_primary(model, messages, stream=False, **kwargs):
            attempts.append(model)
            if model == TEXT_MODELS[0]:
                raise RuntimeError("down")
            return iter([_fake_stream_chunk("ok")])

        provider.client.chat.completions.create.side_effect = always_fail_primary
        list(provider.chat_stream([{"role": "user", "content": "hi"}], "quantum-core-pool"))
        list(provider.chat_stream([{"role": "user", "content": "hi again"}], "quantum-core-pool"))
        self.assertEqual(attempts.count(TEXT_MODELS[0]), 2, "the primary must be retried on every new request")

    def test_streaming_yields_incrementally_across_multiple_chunks(self):
        from chat.providers.nvidia_text_provider import TEXT_MODELS
        provider = self._provider()
        provider.client.chat.completions.create.side_effect = lambda model, messages, stream=False, **kw: iter(
            [_fake_stream_chunk(c) for c in ["Hello", ", ", "world", "!"]]
        ) if model == TEXT_MODELS[0] else iter([])
        out = list(provider.chat_stream([{"role": "user", "content": "hi"}], "quantum-core-pool"))
        self.assertEqual(out, ["Hello", ", ", "world", "!"])

    def test_non_streaming_chat_also_fails_over(self):
        from chat.providers.nvidia_text_provider import TEXT_MODELS
        provider = self._provider()

        def create(model, messages, stream=False, **kwargs):
            if model == TEXT_MODELS[0]:
                raise RuntimeError("down")
            return _fake_response("non-streaming answer")

        provider.client.chat.completions.create.side_effect = create
        result = provider.chat([{"role": "user", "content": "hi"}], "quantum-core-pool")
        self.assertEqual(result, "non-streaming answer")

    def test_vision_delegates_to_the_vision_provider(self):
        provider = self._provider()
        with patch("chat.providers.nvidia_text_provider.ask_vision", return_value="a photo of a cat") as mock_vision:
            result = provider.vision([{"role": "user", "content": "describe this"}], "quantum-core-pool")
        self.assertEqual(result, "a photo of a cat")
        mock_vision.assert_called_once_with(provider.api_key, [{"role": "user", "content": "describe this"}])

    def test_generate_image_is_not_implemented(self):
        """Quantum Core never generates images - that stays Pollinations'
        job (Image Studio), untouched by this rebuild."""
        provider = self._provider()
        with self.assertRaises(NotImplementedError):
            provider.generate_image("a sunset", "quantum-core-pool")


class NvidiaVisionProviderTests(TestCase):
    """End-to-end coverage for chat/providers/nvidia_vision_provider.py's
    fixed VISION_MODELS priority chain, plus its OCR helper - shares the
    same immediate, no-retry, no-memory failover model as the text
    provider. "No Tesseract, no OCR library, everything must use NVIDIA
    Vision" is verified by extract_text_from_image() reusing ask_vision()
    directly rather than any separate implementation."""

    def _client(self):
        return MagicMock()

    def test_fixed_model_list_matches_the_spec_exactly(self):
        from chat.providers.nvidia_vision_provider import VISION_MODELS
        self.assertEqual(VISION_MODELS, [
            "meta/llama-3.2-11b-vision-instruct",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            "nvidia/nemotron-nano-12b-v2-vl",
            "stepfun-ai/step-3.7-flash",
        ])

    def test_primary_model_answers_and_fallbacks_are_never_called(self):
        from chat.providers.nvidia_vision_provider import VISION_MODELS, ask_vision

        def create(model, messages, **kwargs):
            if model == VISION_MODELS[0]:
                return _fake_response("a red apple on a table")
            raise AssertionError(f"fallback model {model} should never be called when the primary succeeds")

        with patch("chat.providers.nvidia_vision_provider._make_client") as mock_make_client:
            mock_make_client.return_value.chat.completions.create.side_effect = create
            result = ask_vision("test-key", [{"role": "user", "content": "what is this?"}])
        self.assertEqual(result, "a red apple on a table")

    def test_on_usage_reaches_ask_vision_but_never_leaks_into_completions_create(self):
        """Regression test: chat/views.py's ask_ai always calls
        ai_vision(..., on_usage=captured_usage.update). Before this fix,
        ask_vision() had no explicit on_usage parameter, so it fell into
        **kwargs and was forwarded straight into
        client.chat.completions.create(**kwargs) - which the OpenAI SDK
        rejects with "unexpected keyword argument 'on_usage'" before any
        HTTP request is ever sent. Confirms the real create() call now
        happens (the request actually reaches the client) and never
        receives on_usage."""
        from chat.providers.nvidia_vision_provider import VISION_MODELS, ask_vision

        received_kwargs = {}

        def create(model, messages, **kwargs):
            received_kwargs.update(kwargs)
            return _fake_response("a photo of a dog")

        with patch("chat.providers.nvidia_vision_provider._make_client") as mock_make_client:
            fake_create = mock_make_client.return_value.chat.completions.create
            fake_create.side_effect = create
            result = ask_vision(
                "test-key",
                [{"role": "user", "content": "what is this?"}],
                on_usage=lambda usage: None,
            )
            fake_create.assert_called_once()

        self.assertEqual(result, "a photo of a dog")
        self.assertNotIn("on_usage", received_kwargs)

    def test_any_error_triggers_immediate_failover_with_a_single_attempt(self):
        from chat.providers.nvidia_vision_provider import VISION_MODELS, ask_vision

        attempts = []

        def create(model, messages, **kwargs):
            attempts.append(model)
            if model == VISION_MODELS[0]:
                raise TimeoutError("timed out")
            return _fake_response("recovered")

        with patch("chat.providers.nvidia_vision_provider._make_client") as mock_make_client:
            mock_make_client.return_value.chat.completions.create.side_effect = create
            result = ask_vision("test-key", [{"role": "user", "content": "what is this?"}])
        self.assertEqual(result, "recovered")
        self.assertEqual(attempts.count(VISION_MODELS[0]), 1, "a failed model must never be retried")

    def test_every_model_exhausted_raises(self):
        from chat.providers.nvidia_vision_provider import ask_vision

        with patch("chat.providers.nvidia_vision_provider._make_client") as mock_make_client:
            mock_make_client.return_value.chat.completions.create.side_effect = RuntimeError("down")
            with self.assertRaises(Exception):
                ask_vision("test-key", [{"role": "user", "content": "what is this?"}])

    def test_extract_text_from_image_reuses_the_ask_vision_chain(self):
        from chat.providers.nvidia_vision_provider import extract_text_from_image

        with patch(
            "chat.providers.nvidia_vision_provider.ask_vision", return_value="Invoice #4471\nTotal: $82.00",
        ) as mock_ask_vision:
            result = extract_text_from_image("test-key", b"fake-image-bytes", "image/png")

        self.assertEqual(result, "Invoice #4471\nTotal: $82.00")
        mock_ask_vision.assert_called_once()
        call_messages = mock_ask_vision.call_args[0][1]
        content = call_messages[0]["content"]
        image_block = next(b for b in content if b["type"] == "image_url")
        self.assertTrue(image_block["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_no_text_found_sentinel_becomes_empty_string(self):
        from chat.providers.nvidia_vision_provider import extract_text_from_image

        with patch("chat.providers.nvidia_vision_provider.ask_vision", return_value="NO_TEXT_FOUND"):
            result = extract_text_from_image("test-key", b"fake-image-bytes")
        self.assertEqual(result, "")

    def test_vision_failure_degrades_to_empty_string_not_an_exception(self):
        """OCR is best-effort context for a chat turn, never a hard
        requirement - every NVIDIA vision model being down must not turn
        an image upload into a visible error."""
        from chat.providers.nvidia_vision_provider import extract_text_from_image

        with patch("chat.providers.nvidia_vision_provider.ask_vision", side_effect=RuntimeError("all models down")):
            result = extract_text_from_image("test-key", b"fake-image-bytes")
        self.assertEqual(result, "")


class QuantumCoreViewIntegrationTests(TestCase):
    """End-to-end through the actual ask_ai view - confirms "quantum-core"
    is a fully wired, selectable model with zero frontend/view changes
    needed, and that the user-visible response never leaks an internal
    NVIDIA model id."""

    def setUp(self):
        self.user = User.objects.create_user(username="quantum_core_user", password="x")
        self.client.force_login(self.user)

    def test_quantum_core_is_registered_and_displayed(self):
        config = get_model_config("quantum-core")
        self.assertEqual(config.provider, "nvidia")
        self.assertIn("Quantum Core", config.display_name)

        models = list_available_models()
        ids = {m["id"] for m in models}
        self.assertIn("quantum-core", ids)

    def test_ask_ai_routes_quantum_core_through_the_text_provider_with_no_leaked_internals(self):
        from chat.providers.nvidia_text_provider import TEXT_MODELS
        from chat.services.provider_manager import get_provider

        provider = get_provider("nvidia")
        fake_client = MagicMock()

        def create(model, messages, stream=False, **kwargs):
            self.assertEqual(model, TEXT_MODELS[0], "the primary model should be tried first")
            return iter([_fake_stream_chunk("Quantum Core says hello.")])

        fake_client.chat.completions.create.side_effect = create
        provider.client = fake_client

        with patch("chat.services.conversation_intelligence.ai_chat") as mock_title_chat:
            mock_title_chat.return_value = "Title"
            response = self.client.post(reverse("ask_ai"), {
                "query": "hello there", "model_id": "quantum-core", "session_id": "",
            })
            self.assertEqual(response.status_code, 200)
            body = b"".join(response.streaming_content).decode()

        self.assertEqual(body, "Quantum Core says hello.")
        for model_id in TEXT_MODELS:
            self.assertNotIn(model_id, body)
        self.assertNotIn("nvidia", body.lower())

    @patch("chat.views.ai_vision")
    def test_image_attachment_with_quantum_core_calls_vision(self, mock_vision):
        mock_vision.return_value = "A handwritten note that says hello."
        img = SimpleUploadedFile("photo.png", b"fake-image-bytes", content_type="image/png")
        response = self.client.post(reverse("ask_ai"), {
            "query": "What does this say?",
            "model_id": "quantum-core",
            "attachment": img,
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "vision")
        self.assertEqual(data["response"], "A handwritten note that says hello.")
        mock_vision.assert_called_once()


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

    def test_history_respects_turn_limit_from_most_recent(self):
        # Part 2 (AI Memory / context optimization) deliberately flipped this
        # from the oldest `limit` turns to the most recent `limit` turns - a
        # long conversation's context window needs to advance as it goes, not
        # stay frozen on the first couple of turns forever. Long-conversation
        # continuity beyond this window comes from conversation_memory's
        # summary injection, covered in its own tests.
        for i in range(5):
            append_turn(self.session, f"q{i}", f"a{i}")
        history = get_conversation_history(self.session, limit=2)
        self.assertEqual(history, [
            {"role": "user", "content": "q3"},
            {"role": "assistant", "content": "a3"},
            {"role": "user", "content": "q4"},
            {"role": "assistant", "content": "a4"},
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

    @patch("chat.views.chat_stream_with_failover")
    def test_new_chat_inherits_active_folder(self, mock_chat_stream):
        """Regression test (Sprint 2 folder bug): a brand-new chat started
        while a folder is the active sidebar filter must be persisted with
        that folder immediately, not just reflected client-side until the
        next page load reverts it."""
        mock_chat_stream.return_value = iter(["ok"])
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max", "folder": "Python"}
        )
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)  # drain the generator so append_turn actually runs
        session = ChatSession.objects.get(user=self.user)
        self.assertEqual(session.folder, "Python")

    @patch("chat.views.chat_stream_with_failover")
    def test_new_chat_without_folder_param_stays_unfiled(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["ok"])
        self.client.force_login(self.user)
        response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max"})
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        session = ChatSession.objects.get(user=self.user)
        self.assertEqual(session.folder, "")

    @patch("chat.views.chat_stream_with_failover")
    def test_continuing_existing_chat_ignores_folder_param(self, mock_chat_stream):
        """The `folder` param must only ever apply at session-creation time -
        continuing an existing chat must never silently refile it just
        because a different folder happens to be the active sidebar filter."""
        mock_chat_stream.return_value = iter(["ok"])
        self.client.force_login(self.user)
        session = ChatSession.objects.create(user=self.user, title="Existing", folder="Work")
        response = self.client.post(reverse("ask_ai"), {
            "query": "hi", "model_id": "cyber-max", "session_id": session.id, "folder": "Python",
        })
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        session.refresh_from_db()
        self.assertEqual(session.folder, "Work")


class ModelAccessControlTests(TestCase):
    """AI Control Center's "per-role model access" - ModelConfig.min_role
    (chat/services/model_registry.py) enforced at the one choke point in
    chat/views.py's ask_ai. Every real registered model defaults to
    min_role="user" (open to everyone) - these tests use a temporary,
    role-restricted model registered via patch.dict so they never depend
    on (or risk breaking) the real model registry's contents."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.admin = User.objects.create_user(username="admin", password="testpass123")
        UserProfile.objects.create(user=self.admin, role=Role.ADMIN)
        self.client.force_login(self.user)

    def test_is_model_allowed_for_user_open_model(self):
        self.assertTrue(is_model_allowed_for_user("cyber-max", self.user))

    def test_is_model_allowed_for_user_unknown_model(self):
        self.assertFalse(is_model_allowed_for_user("not-a-real-model", self.user))

    def test_is_model_allowed_respects_min_role(self):
        restricted = ModelConfig(display_name="Admin Only", provider="groq", actual_model="x", min_role=Role.ADMIN)
        with patch.dict(MODEL_REGISTRY, {"admin-only-test-model": restricted}):
            self.assertFalse(is_model_allowed_for_user("admin-only-test-model", self.user))
            self.assertTrue(is_model_allowed_for_user("admin-only-test-model", self.admin))

    @patch("chat.views.chat_stream_with_failover")
    def test_ask_ai_rejects_role_restricted_model(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["ok"])
        restricted = ModelConfig(display_name="Admin Only", provider="groq", actual_model="x", min_role=Role.ADMIN)
        with patch.dict(MODEL_REGISTRY, {"admin-only-test-model": restricted}):
            response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "admin-only-test-model"})
            data = response.json()
            self.assertEqual(data.get("type"), "error")
            self.assertIn("doesn't have access", data.get("message", ""))
        mock_chat_stream.assert_not_called()

    @patch("chat.views.chat_stream_with_failover")
    def test_ask_ai_allows_admin_for_role_restricted_model(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["ok"])
        self.client.force_login(self.admin)
        restricted = ModelConfig(display_name="Admin Only", provider="groq", actual_model="x", min_role=Role.ADMIN)
        with patch.dict(MODEL_REGISTRY, {"admin-only-test-model": restricted}):
            response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "admin-only-test-model"})
            self.assertEqual(response.status_code, 200)


class AiFeatureFlagEnforcementTests(TestCase):
    """file_upload and web_search (AI Control Center) - both real,
    DB-backed FeatureFlags enforced in chat/views.py's ask_ai, not just
    displayed."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.client.force_login(self.user)

    @patch("chat.views.chat_stream_with_failover")
    def test_file_upload_disabled_rejects_attachment(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["ok"])
        FeatureFlag.objects.create(key="file_upload", enabled=False)
        image = SimpleUploadedFile("x.png", b"fake-bytes", content_type="image/png")
        response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max", "attachment": image})
        data = response.json()
        self.assertEqual(data.get("type"), "error")
        self.assertIn("disabled", data.get("message", ""))

    @patch("chat.views.chat_stream_with_failover")
    @patch("chat.views._get_tavily_search")
    def test_web_search_disabled_skips_tavily(self, mock_search, mock_chat_stream):
        mock_chat_stream.return_value = iter(["ok"])
        FeatureFlag.objects.create(key="web_search", enabled=False)
        response = self.client.post(reverse("ask_ai"), {"query": "what is the latest news today", "model_id": "cyber-max"})
        self.assertEqual(response.status_code, 200)
        mock_search.assert_not_called()


class AttachmentTests(TestCase):
    """Phase 1: file upload -> chat context, and true vision for image attachments."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.client.force_login(self.user)

    def _consume(self, response):
        return b"".join(response.streaming_content).decode()

    @patch("chat.views.chat_stream_with_failover")
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
    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
    def test_text_send_records_usage_event(self, mock_chat_stream):
        mock_chat_stream.return_value = iter(["hello there"])
        response = self.client.post(
            reverse("ask_ai"),
            {"query": "hi", "model_id": "cyber-max", "session_id": self.session.id},
        )
        self._consume(response)
        events = UsageEvent.objects.filter(user=self.user, event_type="chat")
        self.assertEqual(events.count(), 1)
        # Sprint 6: Cyber Max is now routed through the "virtual" pseudo-
        # provider (chat/providers/virtual_provider.py), not "groq" directly
        # - see ModelRegistryTests.test_get_model_config_returns_expected_provider.
        self.assertEqual(events.first().provider, "virtual")
        self.assertTrue(events.first().tokens_are_estimated)

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
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

    @patch("chat.views.chat_stream_with_failover")
    def test_regenerate_records_usage_event(self, mock_chat_stream):
        user_msg, assistant_msg = append_turn(self.session, "hi", "hello")
        mock_chat_stream.return_value = iter(["a better answer"])
        response = self.client.post(
            reverse("regenerate_message", args=[assistant_msg.id]), {"model_id": "cyber-max"}
        )
        self._consume(response)
        self.assertEqual(UsageEvent.objects.filter(user=self.user, event_type="chat").count(), 1)

    @patch("chat.views.chat_stream_with_failover")
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


class SessionOrganizationTests(TestCase):
    """Pin/rename/delete had no test coverage at all before this - covering
    those alongside the new archive/favorite/duplicate/bulk/folder/color
    features rather than leaving old, working behavior untested while only
    testing what's new."""

    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.other_user = User.objects.create_user(username="other", password="testpass123")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user, title="Test Chat")

    def test_pin_toggles(self):
        self.client.post(reverse("pin_session", args=[self.session.id]))
        self.session.refresh_from_db()
        self.assertTrue(self.session.is_pinned)
        self.client.post(reverse("pin_session", args=[self.session.id]))
        self.session.refresh_from_db()
        self.assertFalse(self.session.is_pinned)

    def test_rename(self):
        self.client.post(reverse("rename_session", args=[self.session.id]), {"title": "New Title"})
        self.session.refresh_from_db()
        self.assertEqual(self.session.title, "New Title")

    def test_delete(self):
        self.client.post(reverse("delete_session", args=[self.session.id]))
        self.assertFalse(ChatSession.objects.filter(id=self.session.id).exists())

    def test_cannot_pin_another_users_session(self):
        foreign_session = ChatSession.objects.create(user=self.other_user, title="Not yours")
        response = self.client.post(reverse("pin_session", args=[foreign_session.id]))
        self.assertEqual(response.status_code, 404)

    def test_archive_toggles_and_hides_from_default_list(self):
        response = self.client.post(reverse("toggle_archive_session", args=[self.session.id]))
        self.assertEqual(response.json()["is_archived"], True)
        home_response = self.client.get(reverse("home"))
        self.assertNotIn(self.session, home_response.context["sessions"])
        archived_response = self.client.get(reverse("home") + "?view=archived")
        self.assertIn(self.session, archived_response.context["sessions"])

    def test_favorite_session_toggles(self):
        response = self.client.post(reverse("toggle_favorite_session", args=[self.session.id]))
        self.assertEqual(response.json()["is_favorite"], True)
        self.session.refresh_from_db()
        self.assertTrue(self.session.is_favorite)

    def test_favorite_session_is_distinct_from_image_favorite(self):
        # toggle_favorite_session (whole conversation) must never touch
        # Message.extra_data["favorited"] (one generated image) and vice versa.
        msg = Message.objects.create(session=self.session, role="assistant", content="", extra_data={"type": "image", "favorited": False})
        self.client.post(reverse("toggle_favorite_session", args=[self.session.id]))
        msg.refresh_from_db()
        self.assertFalse(msg.extra_data["favorited"])

    def test_duplicate_session_copies_message_tree(self):
        parent, leaf = append_turn(self.session, "hello", "hi there")
        append_turn(self.session, "follow up", "another reply")
        response = self.client.post(reverse("duplicate_session", args=[self.session.id]))
        data = response.json()
        new_session = ChatSession.objects.get(id=data["session_id"])
        self.assertEqual(new_session.thread.count(), self.session.thread.count())
        self.assertNotEqual(new_session.id, self.session.id)
        self.assertEqual(new_session.title, "Test Chat (copy)")
        # The duplicate's active_leaf must point at ITS OWN copied message,
        # not the original session's.
        self.assertIsNotNone(new_session.active_leaf)
        self.assertNotEqual(new_session.active_leaf_id, self.session.active_leaf_id)

    def test_duplicate_preserves_branch_structure(self):
        user_msg, asst_msg = append_turn(self.session, "hello", "hi")
        # branch: edit the user message (sibling under the same parent)
        sibling_user = Message.objects.create(session=self.session, role="user", content="hello edited", parent=user_msg.parent)
        Message.objects.create(session=self.session, role="assistant", content="hi again", parent=sibling_user)
        response = self.client.post(reverse("duplicate_session", args=[self.session.id]))
        new_session = ChatSession.objects.get(id=response.json()["session_id"])
        # 4 messages total (2 user + 2 assistant), tree structure preserved
        self.assertEqual(new_session.thread.count(), 4)
        roots = [m for m in new_session.thread.all() if m.parent_id is None]
        self.assertEqual(len(roots), 2)  # both user siblings are roots (no parent)

    def test_bulk_delete(self):
        s2 = ChatSession.objects.create(user=self.user, title="Second")
        response = self.client.post(reverse("bulk_session_action"), {
            "action": "delete", "session_ids": [self.session.id, s2.id],
        })
        self.assertEqual(response.json()["count"], 2)
        self.assertFalse(ChatSession.objects.filter(id__in=[self.session.id, s2.id]).exists())

    def test_bulk_archive(self):
        s2 = ChatSession.objects.create(user=self.user, title="Second")
        self.client.post(reverse("bulk_session_action"), {
            "action": "archive", "session_ids": [self.session.id, s2.id],
        })
        self.assertTrue(ChatSession.objects.filter(id=self.session.id, is_archived=True).exists())
        self.assertTrue(ChatSession.objects.filter(id=s2.id, is_archived=True).exists())

    def test_bulk_action_only_affects_own_sessions(self):
        foreign_session = ChatSession.objects.create(user=self.other_user, title="Not yours")
        self.client.post(reverse("bulk_session_action"), {
            "action": "delete", "session_ids": [foreign_session.id],
        })
        self.assertTrue(ChatSession.objects.filter(id=foreign_session.id).exists())

    def test_bulk_action_unknown_action_rejected(self):
        response = self.client.post(reverse("bulk_session_action"), {
            "action": "nuke_everything", "session_ids": [self.session.id],
        })
        self.assertEqual(response.status_code, 400)

    def test_set_folder(self):
        response = self.client.post(reverse("set_session_folder", args=[self.session.id]), {"folder": "Work Stuff"})
        self.assertEqual(response.json()["folder"], "Work Stuff")
        self.session.refresh_from_db()
        self.assertEqual(self.session.folder, "Work Stuff")

    def test_clearing_folder_removes_it(self):
        self.session.folder = "Old Folder"
        self.session.save(update_fields=["folder"])
        self.client.post(reverse("set_session_folder", args=[self.session.id]), {"folder": ""})
        self.session.refresh_from_db()
        self.assertEqual(self.session.folder, "")

    def test_set_valid_color(self):
        response = self.client.post(reverse("set_session_color", args=[self.session.id]), {"color": "blue"})
        self.assertEqual(response.json()["color_label"], "blue")

    def test_set_invalid_color_rejected(self):
        response = self.client.post(reverse("set_session_color", args=[self.session.id]), {"color": "invisible-pink"})
        self.assertEqual(response.status_code, 400)

    def test_chat_home_groups_sessions_by_recency(self):
        old_session = ChatSession.objects.create(user=self.user, title="Old One")
        ChatSession.objects.filter(id=old_session.id).update(created_at=timezone.now() - timedelta(days=60))
        response = self.client.get(reverse("home"))
        self.assertIn(self.session, response.context["grouped_sessions"]["today"])
        self.assertIn(old_session, response.context["grouped_sessions"]["older"])

    def test_chat_home_folder_filter(self):
        self.session.folder = "Work"
        self.session.save(update_fields=["folder"])
        ChatSession.objects.create(user=self.user, title="Not in folder")
        response = self.client.get(reverse("home") + "?folder=Work")
        session_ids = [s.id for s in response.context["sessions"]]
        self.assertEqual(session_ids, [self.session.id])

    def test_chat_home_pinned_and_favorite_sections_are_mutually_exclusive(self):
        self.session.is_pinned = True
        self.session.is_favorite = True
        self.session.save(update_fields=["is_pinned", "is_favorite"])
        response = self.client.get(reverse("home"))
        # A pinned+favorited session shows only in "pinned", never duplicated
        # into the favorites section too.
        self.assertIn(self.session, response.context["pinned_sessions"])
        self.assertNotIn(self.session, response.context["favorite_sessions"])


class MessageContentSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.other_user = User.objects.create_user(username="other", password="testpass123")
        self.client.force_login(self.user)

    def test_search_too_short_returns_nothing(self):
        response = self.client.get(reverse("search_chats"), {"q": "a"})
        self.assertEqual(response.json()["results"], [])

    def test_search_matches_title(self):
        ChatSession.objects.create(user=self.user, title="Unique Title Marker")
        response = self.client.get(reverse("search_chats"), {"q": "Unique Title Marker"})
        results = response.json()["results"]
        self.assertTrue(any(r["match_type"] == "title" for r in results))

    def test_search_matches_message_content(self):
        session = ChatSession.objects.create(user=self.user, title="Some Chat")
        Message.objects.create(session=session, role="user", content="a very distinctive searchable phrase")
        response = self.client.get(reverse("search_chats"), {"q": "distinctive searchable phrase"})
        results = response.json()["results"]
        self.assertTrue(any(r["match_type"] == "message" and r["session_id"] == session.id for r in results))
        self.assertIn("distinctive searchable phrase", results[0]["snippet"])

    def test_search_never_returns_another_users_sessions(self):
        foreign_session = ChatSession.objects.create(user=self.other_user, title="Foreign Unique Marker")
        Message.objects.create(session=foreign_session, role="user", content="foreign unique marker content")
        response = self.client.get(reverse("search_chats"), {"q": "Foreign Unique Marker"})
        self.assertEqual(response.json()["results"], [])

    def test_search_excludes_system_role_messages(self):
        session = ChatSession.objects.create(user=self.user, title="Chat")
        Message.objects.create(session=session, role="system", content="a distinctive system prompt marker")
        response = self.client.get(reverse("search_chats"), {"q": "distinctive system prompt marker"})
        self.assertEqual(response.json()["results"], [])


class DeleteMessageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.other_user = User.objects.create_user(username="other", password="testpass123")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user, title="Chat")

    def test_delete_a_leaf_message(self):
        user_msg, asst_msg = append_turn(self.session, "hello", "hi")
        response = self.client.post(reverse("delete_message", args=[asst_msg.id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Message.objects.filter(id=asst_msg.id).exists())

    def test_deleting_a_message_cascades_to_descendants(self):
        user_msg, asst_msg = append_turn(self.session, "hello", "hi")
        user_msg2, asst_msg2 = append_turn(self.session, "follow up", "another reply")
        self.client.post(reverse("delete_message", args=[user_msg.id]))
        self.assertFalse(Message.objects.filter(id__in=[user_msg.id, asst_msg.id, user_msg2.id, asst_msg2.id]).exists())

    def test_deleting_active_leaf_falls_back_to_latest_remaining_message(self):
        user_msg, asst_msg = append_turn(self.session, "hello", "hi")
        user_msg2, asst_msg2 = append_turn(self.session, "follow up", "another reply")
        self.session.refresh_from_db()
        self.assertEqual(self.session.active_leaf_id, asst_msg2.id)
        self.client.post(reverse("delete_message", args=[asst_msg2.id]))
        self.session.refresh_from_db()
        self.assertEqual(self.session.active_leaf_id, user_msg2.id)

    def test_deleting_entire_tree_leaves_active_leaf_none(self):
        user_msg, asst_msg = append_turn(self.session, "hello", "hi")
        self.client.post(reverse("delete_message", args=[user_msg.id]))
        self.session.refresh_from_db()
        self.assertIsNone(self.session.active_leaf)

    def test_cannot_delete_another_users_message(self):
        foreign_session = ChatSession.objects.create(user=self.other_user, title="Not yours")
        _um, am = append_turn(foreign_session, "hi", "hello")
        response = self.client.post(reverse("delete_message", args=[am.id]))
        self.assertEqual(response.status_code, 404)


class BookmarkMessageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user, title="Chat")

    def test_bookmark_toggles(self):
        _um, am = append_turn(self.session, "hi", "hello")
        response = self.client.post(reverse("bookmark_message", args=[am.id]))
        self.assertTrue(response.json()["bookmarked"])
        response2 = self.client.post(reverse("bookmark_message", args=[am.id]))
        self.assertFalse(response2.json()["bookmarked"])

    def test_bookmark_preserves_other_extra_data(self):
        msg = Message.objects.create(session=self.session, role="assistant", content="", extra_data={"type": "image", "favorited": True})
        self.client.post(reverse("bookmark_message", args=[msg.id]))
        msg.refresh_from_db()
        self.assertTrue(msg.extra_data["favorited"])
        self.assertTrue(msg.extra_data["bookmarked"])


class ContinueMessageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dhruv", password="testpass123")
        self.other_user = User.objects.create_user(username="other", password="testpass123")
        self.client.force_login(self.user)
        self.session = ChatSession.objects.create(user=self.user, title="Chat")

    @patch("chat.views.chat_stream_with_failover")
    def test_continue_appends_to_existing_content(self, mock_chat_stream):
        _um, am = append_turn(self.session, "tell me a story", "Once upon a time")
        mock_chat_stream.return_value = iter([", there was a dragon."])
        response = self.client.post(reverse("continue_message", args=[am.id]), {"model_id": "cyber-max"})
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)  # drain the streaming response
        am.refresh_from_db()
        self.assertEqual(am.content, "Once upon a time, there was a dragon.")

    @patch("chat.views.chat_stream_with_failover")
    def test_continue_does_not_create_a_new_message(self, mock_chat_stream):
        _um, am = append_turn(self.session, "tell me a story", "Once upon a time")
        mock_chat_stream.return_value = iter(["more."])
        count_before = Message.objects.count()
        response = self.client.post(reverse("continue_message", args=[am.id]), {"model_id": "cyber-max"})
        b"".join(response.streaming_content)
        self.assertEqual(Message.objects.count(), count_before)

    def test_cannot_continue_another_users_message(self):
        foreign_session = ChatSession.objects.create(user=self.other_user, title="Not yours")
        _um, am = append_turn(foreign_session, "hi", "hello")
        response = self.client.post(reverse("continue_message", args=[am.id]), {"model_id": "cyber-max"})
        self.assertEqual(response.status_code, 404)


class ProviderFailoverTests(TestCase):
    """Unit-level coverage for chat_stream_with_failover itself (not routed
    through a view) - the view-level tests above only ever mock this
    function wholesale, so they can't exercise its own retry/switch/raise
    logic. Patches chat.services.ai_router.get_provider (the name actually
    bound inside ai_router's own module namespace at import time) rather
    than chat.services.provider_manager.get_provider - patching the latter
    has no effect here, since ai_router already holds its own reference from
    `from chat.services.provider_manager import get_provider`."""

    def test_no_failure_never_switches(self):
        from chat.services.ai_router import chat_stream_with_failover
        with patch("chat.services.ai_router.get_provider") as mock_get_provider:
            mock_get_provider.return_value.chat_stream.return_value = iter(["hello", " world"])
            switches = []
            out = list(chat_stream_with_failover(
                "cyber-max", [{"role": "user", "content": "hi"}], on_switch=switches.append,
            ))
        self.assertEqual(out, ["hello", " world"])
        self.assertEqual(switches, [])

    def test_primary_fails_falls_over_to_next_candidate(self):
        from chat.services.ai_router import chat_stream_with_failover
        from chat.services.model_registry import get_model_config

        def flaky(messages, model, **kwargs):
            if model == get_model_config("cyber-max").actual_model:
                raise RuntimeError("simulated provider outage")
            return iter(["fallback", " response"])

        with patch("chat.services.ai_router.get_provider") as mock_get_provider:
            mock_get_provider.return_value.chat_stream.side_effect = flaky
            switches = []
            out = list(chat_stream_with_failover(
                "cyber-max", [{"role": "user", "content": "hi"}], on_switch=switches.append,
            ))
        self.assertEqual(out, ["fallback", " response"])
        self.assertEqual(switches, ["nova-mind"])

    def test_all_candidates_failing_raises_last_error(self):
        from chat.services.ai_router import chat_stream_with_failover
        with patch("chat.services.ai_router.get_provider") as mock_get_provider:
            mock_get_provider.return_value.chat_stream.side_effect = RuntimeError("total outage")
            with self.assertRaises(RuntimeError):
                list(chat_stream_with_failover(
                    "cyber-max", [{"role": "user", "content": "hi"}], retries_per_model=1,
                ))

    def test_empty_response_is_not_treated_as_a_failure(self):
        from chat.services.ai_router import chat_stream_with_failover
        with patch("chat.services.ai_router.get_provider") as mock_get_provider:
            mock_get_provider.return_value.chat_stream.return_value = iter([])
            switches = []
            out = list(chat_stream_with_failover(
                "cyber-max", [{"role": "user", "content": "hi"}], on_switch=switches.append,
            ))
        self.assertEqual(out, [])
        self.assertEqual(switches, [])

    def test_view_shows_transient_switch_notice_without_persisting_it(self):
        """End-to-end through ask_ai: a switch notice appears in the live
        stream but the saved Message.content stays exactly the model's real
        output - a stray literal "_(Switched to...)_ " permanently glued
        onto every future reload of this reply would be a real regression."""
        user = get_user_model().objects.create_user(username="failover_user", password="x")
        self.client.force_login(user)

        def flaky(messages, model, **kwargs):
            from chat.services.model_registry import get_model_config
            if model == get_model_config("cyber-max").actual_model:
                raise RuntimeError("simulated outage")
            return iter(["real", " answer"])

        with patch("chat.services.ai_router.get_provider") as mock_get_provider, \
             patch("chat.services.conversation_intelligence.ai_chat") as mock_title_chat:
            mock_get_provider.return_value.chat_stream.side_effect = flaky
            mock_title_chat.return_value = "Some Title"
            response = self.client.post(
                reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max"},
            )
            body = b"".join(response.streaming_content).decode()

        self.assertIn("Switched to", body)
        saved = Message.objects.filter(session__user=user, role="assistant").first()
        self.assertEqual(saved.content, "real answer")
        self.assertNotIn("Switched to", saved.content)


class SmartModelRoutingTests(TestCase):
    """Part 3 - resolve_model_id/choose_model unit coverage, plus one
    end-to-end check through ask_ai confirming "auto" never reaches
    get_model_config (which would 400 with "Invalid model selection")."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="router_user", password="x")
        self.client.force_login(self.user)

    def test_manual_model_id_passes_through_unchanged(self):
        from chat.services.smart_router import resolve_model_id
        self.assertEqual(resolve_model_id("sky-net-mini", "anything", False, "cyber-max"), "sky-net-mini")

    def test_short_query_routes_to_fast_model(self):
        from chat.services.smart_router import resolve_model_id, FAST_MODEL
        self.assertEqual(resolve_model_id("auto", "hi", False, "cyber-max"), FAST_MODEL)

    def test_complex_query_routes_to_capable_model(self):
        from chat.services.smart_router import resolve_model_id, CAPABLE_MODEL
        long_query = "Please explain in detail, step by step, the tradeoffs of eventual consistency. " * 3
        self.assertEqual(resolve_model_id("auto", long_query, False, "nova-mind"), CAPABLE_MODEL)

    def test_image_attachment_routes_to_vision_model(self):
        from chat.services.smart_router import resolve_model_id, VISION_MODEL
        self.assertEqual(resolve_model_id("auto", "what is this?", True, "cyber-max"), VISION_MODEL)

    def test_ordinary_query_falls_back_to_users_default_model(self):
        from chat.services.smart_router import resolve_model_id
        self.assertEqual(
            resolve_model_id("auto", "What's a good approach for organizing my notes app?", False, "sky-net-mini"),
            "sky-net-mini",
        )

    def test_ask_ai_with_auto_model_id_does_not_error(self):
        with patch("chat.services.ai_router.get_provider") as mock_get_provider, \
             patch("chat.services.conversation_intelligence.ai_chat") as mock_title_chat:
            mock_get_provider.return_value.chat_stream.return_value = iter(["ok"])
            mock_title_chat.return_value = "Some Title"
            response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "auto"})
            self.assertEqual(response.status_code, 200)
            body = b"".join(response.streaming_content).decode()
        self.assertNotIn("Invalid model selection", body)
        self.assertEqual(Message.objects.filter(session__user=self.user, role="assistant").first().content, "ok")


class ConversationMemoryTests(TestCase):
    """Part 2 - AI memory: context-window sizing, summarization triggering/
    merging, and the memory_enabled-gated fact extraction/recall loop."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="memory_user", password="x")
        self.session = ChatSession.objects.create(user=self.user, title="Memory chat")

    def test_build_context_messages_shape(self):
        from chat.services.conversation_memory import build_context_messages
        append_turn(self.session, "hi", "hello")
        messages = build_context_messages(self.session, "how are you", "SYS")
        self.assertEqual(messages[0], {"role": "system", "content": "SYS"})
        self.assertEqual(messages[-1], {"role": "user", "content": "how are you"})

    def test_no_summarization_below_threshold(self):
        from chat.services.conversation_memory import maybe_summarize_session
        append_turn(self.session, "hi", "hello")
        with patch("chat.services.conversation_memory.ai_chat") as mock_ai_chat:
            maybe_summarize_session(self.session)
        mock_ai_chat.assert_not_called()
        self.session.refresh_from_db()
        self.assertEqual(self.session.summary, "")

    def test_summarization_triggers_past_threshold_and_injects_into_context(self):
        from chat.services.conversation_memory import maybe_summarize_session, build_context_messages
        for i in range(15):
            append_turn(self.session, f"q{i}", f"a{i}")
        with patch("chat.services.conversation_memory.ai_chat") as mock_ai_chat:
            mock_ai_chat.return_value = "Compact summary of the early turns."
            maybe_summarize_session(self.session)
            self.assertTrue(mock_ai_chat.called)
            self.assertEqual(mock_ai_chat.call_args[0][0], "nova-mind")

        self.session.refresh_from_db()
        self.assertEqual(self.session.summary, "Compact summary of the early turns.")
        self.assertEqual(self.session.summary_message_count, 30)

        messages = build_context_messages(self.session, "new question", "SYS")
        system_contents = [m["content"] for m in messages if m["role"] == "system"]
        self.assertTrue(any("Compact summary" in c for c in system_contents))

    def test_fact_extraction_is_gated_by_caller_not_automatic(self):
        """extract_and_store_facts has no memory_enabled check of its own -
        it's the caller's job (ask_ai only calls it when profile.memory_enabled
        is True). Verifies the function itself still runs and stores facts
        when invoked directly, and that the one-shot flag then blocks re-runs."""
        from chat.services.conversation_memory import extract_and_store_facts
        for i in range(3):
            append_turn(self.session, f"q{i}", f"a{i}")

        with patch("chat.services.conversation_memory.ai_chat") as mock_ai_chat:
            mock_ai_chat.return_value = "Works as a backend engineer\nPrefers concise answers"
            extract_and_store_facts(self.user, self.session)

        facts = set(UserFact.objects.filter(user=self.user).values_list("fact", flat=True))
        self.assertEqual(facts, {"Works as a backend engineer", "Prefers concise answers"})

        self.session.refresh_from_db()
        self.assertTrue(self.session.facts_extracted)

        with patch("chat.services.conversation_memory.ai_chat") as mock_ai_chat_again:
            extract_and_store_facts(self.user, self.session)
        mock_ai_chat_again.assert_not_called()

    def test_fact_extraction_none_response_stores_nothing(self):
        from chat.services.conversation_memory import extract_and_store_facts
        for i in range(3):
            append_turn(self.session, f"q{i}", f"a{i}")
        with patch("chat.services.conversation_memory.ai_chat") as mock_ai_chat:
            mock_ai_chat.return_value = "NONE"
            extract_and_store_facts(self.user, self.session)
        self.assertEqual(UserFact.objects.filter(user=self.user).count(), 0)

    def test_get_user_memory_context_empty_when_no_facts(self):
        from chat.services.conversation_memory import get_user_memory_context
        self.assertEqual(get_user_memory_context(self.user), "")

    def test_get_user_memory_context_formats_stored_facts(self):
        from chat.services.conversation_memory import get_user_memory_context
        UserFact.objects.create(user=self.user, fact="Name is Alex")
        context = get_user_memory_context(self.user)
        self.assertIn("Name is Alex", context)

    def test_clear_memory_deletes_only_this_users_facts(self):
        other = get_user_model().objects.create_user(username="other_memory_user", password="x")
        UserFact.objects.create(user=self.user, fact="mine")
        UserFact.objects.create(user=other, fact="not mine")
        self.client.force_login(self.user)
        response = self.client.post(reverse("clear_memory"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(UserFact.objects.filter(user=self.user).count(), 0)
        self.assertEqual(UserFact.objects.filter(user=other).count(), 1)


class ConversationIntelligenceTests(TestCase):
    """Part 6 - AI-generated titles (once, first-turn-only, never overwriting
    a user's own rename), on-demand follow-up suggestions, and the
    word-overlap "related conversations" heuristic."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="intel_user", password="x")
        self.client.force_login(self.user)

    def test_generic_title_gets_upgraded_on_first_turn(self):
        from chat.services.conversation_intelligence import maybe_generate_smart_title
        session = ChatSession.objects.create(user=self.user, title="New Chat")
        with patch("chat.services.conversation_intelligence.ai_chat") as mock_ai_chat:
            mock_ai_chat.return_value = "Trip Planning Ideas"
            maybe_generate_smart_title(session, "help me plan a trip", "Sure, where to?")
        session.refresh_from_db()
        self.assertEqual(session.title, "Trip Planning Ideas")

    def test_user_renamed_title_is_never_overwritten(self):
        from chat.services.conversation_intelligence import maybe_generate_smart_title
        session = ChatSession.objects.create(user=self.user, title="My Custom Name")
        with patch("chat.services.conversation_intelligence.ai_chat") as mock_ai_chat:
            maybe_generate_smart_title(session, "hello", "hi there")
        mock_ai_chat.assert_not_called()
        session.refresh_from_db()
        self.assertEqual(session.title, "My Custom Name")

    def test_title_only_generated_once_per_session_via_ask_ai(self):
        with patch("chat.services.ai_router.get_provider") as mock_get_provider, \
             patch("chat.services.conversation_intelligence.ai_chat") as mock_title_chat:
            mock_get_provider.return_value.chat_stream.return_value = iter(["answer one"])
            mock_title_chat.return_value = "Generated Title"
            r1 = self.client.post(reverse("ask_ai"), {"query": "first question", "model_id": "cyber-max"})
            b"".join(r1.streaming_content)

        session = ChatSession.objects.get(user=self.user)
        self.assertEqual(session.title, "Generated Title")

        with patch("chat.services.ai_router.get_provider") as mock_get_provider, \
             patch("chat.services.conversation_intelligence.ai_chat") as mock_title_chat:
            mock_get_provider.return_value.chat_stream.return_value = iter(["answer two"])
            r2 = self.client.post(
                reverse("ask_ai"), {"query": "second question", "model_id": "cyber-max", "session_id": session.id},
            )
            b"".join(r2.streaming_content)
            mock_title_chat.assert_not_called()

    def test_suggest_followups_endpoint(self):
        session = ChatSession.objects.create(user=self.user, title="Chat")
        append_turn(session, "hi", "hello there")
        with patch("chat.services.conversation_intelligence.ai_chat") as mock_ai_chat:
            mock_ai_chat.return_value = "Follow-up one\nFollow-up two\nFollow-up three"
            response = self.client.get(reverse("session_suggest_followups", args=[session.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["suggestions"]), 3)

    def test_suggest_followups_empty_for_session_with_no_reply_yet(self):
        session = ChatSession.objects.create(user=self.user, title="Empty chat")
        response = self.client.get(reverse("session_suggest_followups", args=[session.id]))
        self.assertEqual(response.json()["suggestions"], [])

    def test_cannot_suggest_followups_for_another_users_session(self):
        other = get_user_model().objects.create_user(username="other_intel_user", password="x")
        foreign_session = ChatSession.objects.create(user=other, title="Not yours")
        response = self.client.get(reverse("session_suggest_followups", args=[foreign_session.id]))
        self.assertEqual(response.status_code, 404)

    def test_suggest_followups_uses_specified_message_not_active_leaf(self):
        """Regression test (Sprint 2 follow-up bug): clicking "Suggest
        Follow-ups" on an older reply that is no longer the session's active
        leaf (e.g. after a regenerate created a newer sibling) must generate
        suggestions from THAT reply's own content, not silently substitute
        whatever the session's current active leaf happens to be."""
        session = ChatSession.objects.create(user=self.user, title="Chat")
        _user_msg, old_assistant_msg = append_turn(session, "hi", "the old reply about cats")
        regenerate_assistant_reply(old_assistant_msg, "the new reply about dogs")

        with patch("chat.services.conversation_intelligence.ai_chat") as mock_ai_chat:
            mock_ai_chat.return_value = "Follow-up A\nFollow-up B"
            response = self.client.get(
                reverse("session_suggest_followups", args=[session.id]),
                {"message_id": old_assistant_msg.id},
            )
        self.assertEqual(response.status_code, 200)
        sent_messages = mock_ai_chat.call_args[0][1]
        combined = " ".join(m["content"] for m in sent_messages)
        self.assertIn("cats", combined)
        self.assertNotIn("dogs", combined)

    def test_suggest_followups_dedupes_repeated_suggestions(self):
        session = ChatSession.objects.create(user=self.user, title="Chat")
        append_turn(session, "hi", "hello there")
        with patch("chat.services.conversation_intelligence.ai_chat") as mock_ai_chat:
            mock_ai_chat.return_value = "Tell me more\nTell me more\nSomething else"
            response = self.client.get(reverse("session_suggest_followups", args=[session.id]))
        self.assertEqual(response.json()["suggestions"], ["Tell me more", "Something else"])

    def test_suggest_followups_retries_on_failure_with_different_model(self):
        """Regression test: MEMORY_MODEL_ID (nova-mind) and the default chat
        model share the same Groq API key/daily quota, so a transient failure
        (e.g. that quota being exhausted by ordinary chat traffic) must not
        immediately surface as "no suggestions" - a second attempt against a
        different model in the fallback chain must run automatically first."""
        session = ChatSession.objects.create(user=self.user, title="Chat")
        append_turn(session, "hi", "hello there")
        with patch("chat.services.conversation_intelligence.ai_chat") as mock_ai_chat:
            mock_ai_chat.side_effect = [
                Exception("rate_limit_exceeded"),
                "Follow-up one\nFollow-up two\nFollow-up three",
            ]
            response = self.client.get(reverse("session_suggest_followups", args=[session.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["suggestions"]), 3)
        self.assertEqual(mock_ai_chat.call_count, 2)
        first_model = mock_ai_chat.call_args_list[0][0][0]
        second_model = mock_ai_chat.call_args_list[1][0][0]
        self.assertNotEqual(first_model, second_model)

    def test_suggest_followups_never_empty_even_when_every_ai_attempt_fails(self):
        """"No suggestions" must never reach the user while there's a real
        reply to derive from - after both AI attempts fail (e.g. a full
        provider outage), suggest_followups falls back to 3 suggestions
        deterministically derived from the actual reply text."""
        session = ChatSession.objects.create(user=self.user, title="Chat")
        _um, am = append_turn(
            session, "hi",
            "Django's ORM lets you query the database using Python. "
            "It supports filtering, joins, and aggregation. "
            "select_related() and prefetch_related() optimize related lookups.",
        )
        with patch("chat.services.conversation_intelligence.ai_chat") as mock_ai_chat:
            mock_ai_chat.side_effect = Exception("total outage")
            response = self.client.get(
                reverse("session_suggest_followups", args=[session.id]), {"message_id": am.id},
            )
        self.assertEqual(response.status_code, 200)
        suggestions = response.json()["suggestions"]
        self.assertEqual(len(suggestions), 3)
        self.assertTrue(all(s.strip() for s in suggestions))
        # Genuinely derived from the reply, not a static/generic list.
        combined = " ".join(suggestions).lower()
        self.assertTrue("django" in combined or "orm" in combined or "select_related" in combined)
        self.assertEqual(mock_ai_chat.call_count, 2)

    def test_suggest_followups_fallback_handles_very_short_reply(self):
        """Even a reply too short to contain 3 distinct sentences must still
        produce exactly 3 suggestions (by reusing real content), never fewer
        and never a blank/generic filler."""
        from chat.services.conversation_intelligence import _derive_followups_from_reply
        suggestions = _derive_followups_from_reply("Yes.")
        self.assertEqual(len(suggestions), 3)
        self.assertTrue(all(s.strip() for s in suggestions))

    def test_suggest_followups_survives_20_consecutive_cycles(self):
        """Validation scenario from the bug report: assistant reply -> 3
        suggestions -> click -> assistant reply -> 3 NEW suggestions,
        repeated 20 times, must never once show zero suggestions - even
        with every other AI attempt simulated as a total failure."""
        session = ChatSession.objects.create(user=self.user, title="Chat")
        for i in range(20):
            _um, am = append_turn(
                session, f"question {i}",
                f"This is assistant reply number {i} about Django topic {i}. "
                f"It covers detail A and detail B for iteration {i}.",
            )
            with patch("chat.services.conversation_intelligence.ai_chat") as mock_ai_chat:
                if i % 2 == 0:
                    mock_ai_chat.return_value = f"Follow-up A{i}\nFollow-up B{i}\nFollow-up C{i}"
                else:
                    mock_ai_chat.side_effect = Exception(f"simulated outage {i}")
                response = self.client.get(
                    reverse("session_suggest_followups", args=[session.id]), {"message_id": am.id},
                )
            self.assertEqual(response.status_code, 200, f"cycle {i} failed")
            suggestions = response.json()["suggestions"]
            self.assertEqual(len(suggestions), 3, f"cycle {i} did not return 3 suggestions: {suggestions}")

    def test_related_conversations_matches_on_title_word_overlap(self):
        session = ChatSession.objects.create(user=self.user, title="Django REST API design")
        related = ChatSession.objects.create(user=self.user, title="REST API authentication in Django")
        unrelated = ChatSession.objects.create(user=self.user, title="Baking sourdough bread")
        response = self.client.get(reverse("session_related_conversations", args=[session.id]))
        result_ids = {r["id"] for r in response.json()["results"]}
        self.assertIn(related.id, result_ids)
        self.assertNotIn(unrelated.id, result_ids)

    def test_related_conversations_excludes_archived_sessions(self):
        session = ChatSession.objects.create(user=self.user, title="Django REST API design")
        ChatSession.objects.create(user=self.user, title="Django REST API testing", is_archived=True)
        response = self.client.get(reverse("session_related_conversations", args=[session.id]))
        self.assertEqual(response.json()["results"], [])


class PromptLibraryTests(TestCase):
    """Part 5 - SavedPrompt CRUD, search/category/favorite filtering, use_count
    tracking, and the recent-prompts view that reads real message history
    instead of a separate log."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="prompt_user", password="x")
        self.other_user = get_user_model().objects.create_user(username="other_prompt_user", password="x")
        self.client.force_login(self.user)

    def test_create_prompt(self):
        response = self.client.post(reverse("create_saved_prompt"), {
            "title": "Code Review", "content": "Review this: ", "category": "Coding",
        })
        self.assertEqual(response.status_code, 200)
        prompt = SavedPrompt.objects.get(user=self.user)
        self.assertEqual(prompt.title, "Code Review")
        self.assertEqual(prompt.category, "Coding")

    def test_create_rejects_empty_content(self):
        response = self.client.post(reverse("create_saved_prompt"), {"title": "Empty", "content": ""})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(SavedPrompt.objects.filter(user=self.user).exists())

    def test_create_falls_back_to_content_prefix_when_title_blank(self):
        response = self.client.post(reverse("create_saved_prompt"), {"content": "A prompt with no explicit title"})
        prompt_id = response.json()["prompt"]["id"]
        prompt = SavedPrompt.objects.get(id=prompt_id)
        self.assertTrue(prompt.title)

    def test_search_matches_title_and_content(self):
        SavedPrompt.objects.create(user=self.user, title="Alpha", content="something about bugs")
        SavedPrompt.objects.create(user=self.user, title="Beta", content="unrelated text")
        response = self.client.get(reverse("saved_prompts_list"), {"q": "bugs"})
        titles = [p["title"] for p in response.json()["results"]]
        self.assertEqual(titles, ["Alpha"])

    def test_category_filter(self):
        SavedPrompt.objects.create(user=self.user, title="A", content="x", category="Coding")
        SavedPrompt.objects.create(user=self.user, title="B", content="y", category="Writing")
        response = self.client.get(reverse("saved_prompts_list"), {"category": "Writing"})
        titles = [p["title"] for p in response.json()["results"]]
        self.assertEqual(titles, ["B"])

    def test_favorites_filter(self):
        SavedPrompt.objects.create(user=self.user, title="Fav", content="x", is_favorite=True)
        SavedPrompt.objects.create(user=self.user, title="NotFav", content="y")
        response = self.client.get(reverse("saved_prompts_list"), {"favorites": "1"})
        titles = [p["title"] for p in response.json()["results"]]
        self.assertEqual(titles, ["Fav"])

    def test_use_prompt_increments_count_and_returns_content(self):
        prompt = SavedPrompt.objects.create(user=self.user, title="A", content="the content")
        response = self.client.post(reverse("use_saved_prompt", args=[prompt.id]))
        self.assertEqual(response.json()["content"], "the content")
        prompt.refresh_from_db()
        self.assertEqual(prompt.use_count, 1)
        self.client.post(reverse("use_saved_prompt", args=[prompt.id]))
        prompt.refresh_from_db()
        self.assertEqual(prompt.use_count, 2)

    def test_update_prompt_fields(self):
        prompt = SavedPrompt.objects.create(user=self.user, title="Old", content="x", category="A")
        response = self.client.post(reverse("update_saved_prompt", args=[prompt.id]), {
            "title": "New", "category": "B", "is_favorite": "1",
        })
        self.assertEqual(response.status_code, 200)
        prompt.refresh_from_db()
        self.assertEqual(prompt.title, "New")
        self.assertEqual(prompt.category, "B")
        self.assertTrue(prompt.is_favorite)

    def test_delete_prompt(self):
        prompt = SavedPrompt.objects.create(user=self.user, title="A", content="x")
        response = self.client.post(reverse("delete_saved_prompt", args=[prompt.id]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SavedPrompt.objects.filter(id=prompt.id).exists())

    def test_cannot_access_another_users_prompts(self):
        foreign_prompt = SavedPrompt.objects.create(user=self.other_user, title="Not yours", content="x")
        self.assertEqual(self.client.post(reverse("delete_saved_prompt", args=[foreign_prompt.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse("update_saved_prompt", args=[foreign_prompt.id]), {"title": "hi"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("use_saved_prompt", args=[foreign_prompt.id])).status_code, 404)

    def test_list_only_returns_own_prompts(self):
        SavedPrompt.objects.create(user=self.user, title="Mine", content="x")
        SavedPrompt.objects.create(user=self.other_user, title="Not mine", content="y")
        response = self.client.get(reverse("saved_prompts_list"))
        titles = [p["title"] for p in response.json()["results"]]
        self.assertEqual(titles, ["Mine"])

    def test_recent_prompts_reads_from_message_history_and_dedupes(self):
        session = ChatSession.objects.create(user=self.user, title="Chat")
        append_turn(session, "What is Django?", "A web framework")
        append_turn(session, "What is Python?", "A programming language")
        append_turn(session, "What is Django?", "A web framework")
        response = self.client.get(reverse("recent_prompts"))
        contents = [r["content"] for r in response.json()["results"]]
        self.assertEqual(len(contents), 2)
        self.assertIn("What is Django?", contents)
        self.assertIn("What is Python?", contents)

    def test_recent_prompts_only_own_history(self):
        other_session = ChatSession.objects.create(user=self.other_user, title="Other chat")
        append_turn(other_session, "Someone else's question", "answer")
        response = self.client.get(reverse("recent_prompts"))
        self.assertEqual(response.json()["results"], [])


class SuccessErrorRateTests(TestCase):
    """Part 7 - failed AI calls now record a UsageEvent(success=False)
    alongside the pre-existing successful ones, so success/error rate is a
    real aggregate. Also guards the quota-isolation requirement: a failed
    call must never itself count against check_rate_limit/check_daily_limit."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="rate_user", password="x")
        self.client.force_login(self.user)

    def test_failed_chat_request_records_unsuccessful_usage_event(self):
        with patch("chat.services.ai_router.get_provider") as mock_get_provider:
            mock_get_provider.return_value.chat_stream.side_effect = RuntimeError("outage")
            response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max"})
            b"".join(response.streaming_content)

        event = UsageEvent.objects.get(user=self.user)
        self.assertFalse(event.success)
        self.assertEqual(event.prompt_tokens, 0)
        self.assertEqual(event.estimated_cost_usd, 0)

    def test_successful_request_still_records_success_true(self):
        with patch("chat.services.ai_router.get_provider") as mock_get_provider, \
             patch("chat.services.conversation_intelligence.ai_chat") as mock_title:
            mock_get_provider.return_value.chat_stream.return_value = iter(["a real reply"])
            mock_title.return_value = "Title"
            response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max"})
            b"".join(response.streaming_content)

        event = UsageEvent.objects.get(user=self.user)
        self.assertTrue(event.success)

    def test_failed_request_does_not_consume_rate_limit_quota(self):
        from chat.services.usage import check_rate_limit
        with patch("chat.services.ai_router.get_provider") as mock_get_provider:
            mock_get_provider.return_value.chat_stream.side_effect = RuntimeError("outage")
            for _ in range(5):
                response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max"})
                b"".join(response.streaming_content)
        self.assertTrue(check_rate_limit(self.user))

    def test_failed_request_does_not_consume_daily_quota(self):
        from chat.services.usage import check_daily_limit
        with patch("chat.services.ai_router.get_provider") as mock_get_provider:
            mock_get_provider.return_value.chat_stream.side_effect = RuntimeError("outage")
            response = self.client.post(reverse("ask_ai"), {"query": "hi", "model_id": "cyber-max"})
            b"".join(response.streaming_content)
        allowed, reason = check_daily_limit(self.user, "chat")
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_analytics_success_rate_reflects_mixed_outcomes(self):
        UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat", success=True)
        UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat", success=True)
        UsageEvent.objects.create(user=self.user, provider="groq", model_id="cyber-max", event_type="chat", success=False)
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["success_rate"], 66.7)
        self.assertEqual(response.context["failed_attempts"], 1)
        self.assertEqual(response.context["total_attempts"], 3)
        # total_requests (the pre-existing metric) stays scoped to
        # successes only - it must not be inflated by the failed attempt.
        self.assertEqual(response.context["total_requests"], 2)

    def test_analytics_success_rate_defaults_to_100_with_no_events(self):
        response = self.client.get(reverse("analytics_dashboard"))
        self.assertEqual(response.context["success_rate"], 100.0)


class BackgroundProcessingCommandTests(TestCase):
    """Part 8 - the two management commands meant to run on a schedule
    (Render Cron Job) rather than inline in a request."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="cmd_user", password="x")

    def test_summarize_stale_sessions_only_touches_sessions_past_threshold(self):
        from django.core.management import call_command
        from chat.services.conversation_memory import SUMMARIZE_EVERY_N_MESSAGES

        stale_session = ChatSession.objects.create(user=self.user, title="Stale")
        for i in range(SUMMARIZE_EVERY_N_MESSAGES // 2 + 1):
            append_turn(stale_session, f"q{i}", f"a{i}")

        fresh_session = ChatSession.objects.create(user=self.user, title="Fresh")
        append_turn(fresh_session, "hi", "hello")

        with patch("chat.services.conversation_memory.ai_chat") as mock_ai_chat:
            mock_ai_chat.return_value = "Batch summary."
            call_command("summarize_stale_sessions")

        stale_session.refresh_from_db()
        fresh_session.refresh_from_db()
        self.assertTrue(stale_session.summary)
        self.assertFalse(fresh_session.summary)

    def test_summarize_stale_sessions_respects_limit(self):
        from django.core.management import call_command
        from chat.services.conversation_memory import SUMMARIZE_EVERY_N_MESSAGES

        for n in range(3):
            s = ChatSession.objects.create(user=self.user, title=f"Stale {n}")
            for i in range(SUMMARIZE_EVERY_N_MESSAGES // 2 + 1):
                append_turn(s, f"q{i}", f"a{i}")

        with patch("chat.services.conversation_memory.ai_chat") as mock_ai_chat:
            mock_ai_chat.return_value = "Batch summary."
            call_command("summarize_stale_sessions", limit=1)

        summarized_count = ChatSession.objects.filter(user=self.user).exclude(summary="").count()
        self.assertEqual(summarized_count, 1)

    def test_cleanup_removes_expired_sessions_and_orphaned_user_sessions(self):
        from django.core.management import call_command
        from django.contrib.sessions.models import Session

        Session.objects.create(
            session_key="expiredkey123", session_data="x",
            expire_date=timezone.now() - timedelta(days=1),
        )
        UserSession.objects.create(user=self.user, session_key="expiredkey123", ip_address="1.2.3.4")
        UserSession.objects.create(user=self.user, session_key="never-existed", ip_address="1.2.3.4")

        call_command("cleanup_stale_data")

        self.assertFalse(Session.objects.filter(session_key="expiredkey123").exists())
        self.assertEqual(UserSession.objects.filter(user=self.user).count(), 0)

    def test_cleanup_deletes_old_resolved_errors_but_keeps_unresolved_and_recent(self):
        from django.core.management import call_command

        old_resolved = ErrorLog.objects.create(category="chat_provider", message="old", resolved=True)
        ErrorLog.objects.filter(id=old_resolved.id).update(resolved_at=timezone.now() - timedelta(days=100))

        recent_resolved = ErrorLog.objects.create(category="chat_provider", message="recent", resolved=True)
        ErrorLog.objects.filter(id=recent_resolved.id).update(resolved_at=timezone.now() - timedelta(days=5))

        old_unresolved = ErrorLog.objects.create(category="chat_provider", message="unresolved", resolved=False)
        ErrorLog.objects.filter(id=old_unresolved.id).update(last_seen=timezone.now() - timedelta(days=300))

        call_command("cleanup_stale_data")

        self.assertFalse(ErrorLog.objects.filter(id=old_resolved.id).exists())
        self.assertTrue(ErrorLog.objects.filter(id=recent_resolved.id).exists())
        self.assertTrue(ErrorLog.objects.filter(id=old_unresolved.id).exists())


class FolderManagementTests(TestCase):
    """UI-polish task, Part 3 - full folder workflow: create, rename
    (including merge-on-collision), delete (unfiles, never deletes chats),
    recolor, and cross-user isolation. Membership stays on
    ChatSession.folder (a string) - Folder is metadata only, so these tests
    also guard that the two never drift out of sync."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="folder_user", password="x")
        self.other_user = get_user_model().objects.create_user(username="other_folder_user", password="x")
        self.client.force_login(self.user)

    def test_create_folder(self):
        response = self.client.post(reverse("create_folder"), {"name": "Work"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Folder.objects.filter(user=self.user, name="Work").exists())

    def test_create_duplicate_folder_rejected(self):
        Folder.objects.create(user=self.user, name="Work")
        response = self.client.post(reverse("create_folder"), {"name": "Work"})
        self.assertEqual(response.status_code, 400)

    def test_create_folder_rejects_blank_name(self):
        response = self.client.post(reverse("create_folder"), {"name": "  "})
        self.assertEqual(response.status_code, 400)

    def test_moving_chat_into_folder_lazily_creates_metadata_row(self):
        session = ChatSession.objects.create(user=self.user, title="Chat")
        response = self.client.post(reverse("set_session_folder", args=[session.id]), {"folder": "Ideas"})
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.folder, "Ideas")
        self.assertTrue(Folder.objects.filter(user=self.user, name="Ideas").exists())

    def test_rename_folder_updates_chats_and_metadata(self):
        Folder.objects.create(user=self.user, name="Work", color="blue")
        session = ChatSession.objects.create(user=self.user, title="Chat", folder="Work")
        response = self.client.post(reverse("rename_folder"), {"old_name": "Work", "new_name": "Projects"})
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.folder, "Projects")
        self.assertFalse(Folder.objects.filter(user=self.user, name="Work").exists())
        renamed = Folder.objects.get(user=self.user, name="Projects")
        self.assertEqual(renamed.color, "blue")

    def test_rename_folder_onto_existing_name_merges(self):
        Folder.objects.create(user=self.user, name="Work")
        Folder.objects.create(user=self.user, name="Projects")
        s1 = ChatSession.objects.create(user=self.user, title="A", folder="Work")
        s2 = ChatSession.objects.create(user=self.user, title="B", folder="Projects")
        response = self.client.post(reverse("rename_folder"), {"old_name": "Work", "new_name": "Projects"})
        self.assertEqual(response.status_code, 200)
        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertEqual(s1.folder, "Projects")
        self.assertEqual(s2.folder, "Projects")
        self.assertEqual(Folder.objects.filter(user=self.user, name__in=["Work", "Projects"]).count(), 1)

    def test_delete_folder_unfiles_chats_without_deleting_them(self):
        Folder.objects.create(user=self.user, name="Work")
        s1 = ChatSession.objects.create(user=self.user, title="A", folder="Work")
        s2 = ChatSession.objects.create(user=self.user, title="B", folder="Work")
        response = self.client.post(reverse("delete_folder"), {"name": "Work"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unfiled"], 2)
        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertEqual(s1.folder, "")
        self.assertEqual(s2.folder, "")
        self.assertTrue(ChatSession.objects.filter(id__in=[s1.id, s2.id]).count() == 2)
        self.assertFalse(Folder.objects.filter(user=self.user, name="Work").exists())

    def test_set_folder_color(self):
        Folder.objects.create(user=self.user, name="Work")
        response = self.client.post(reverse("set_folder_color"), {"name": "Work", "color": "green"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Folder.objects.get(user=self.user, name="Work").color, "green")

    def test_set_folder_color_rejects_invalid_color(self):
        Folder.objects.create(user=self.user, name="Work")
        response = self.client.post(reverse("set_folder_color"), {"name": "Work", "color": "invalid"})
        self.assertEqual(response.status_code, 400)

    def test_folder_actions_are_scoped_to_own_user(self):
        Folder.objects.create(user=self.other_user, name="Secret")
        ChatSession.objects.create(user=self.other_user, title="Not yours", folder="Secret")

        self.client.post(reverse("delete_folder"), {"name": "Secret"})
        self.assertTrue(Folder.objects.filter(user=self.other_user, name="Secret").exists())

        self.client.post(reverse("rename_folder"), {"old_name": "Secret", "new_name": "Hacked"})
        self.assertTrue(Folder.objects.filter(user=self.other_user, name="Secret").exists())
        self.assertFalse(Folder.objects.filter(user=self.other_user, name="Hacked").exists())

    def test_home_lists_folders_with_color_and_count(self):
        Folder.objects.create(user=self.user, name="Work", color="blue")
        ChatSession.objects.create(user=self.user, title="A", folder="Work")
        ChatSession.objects.create(user=self.user, title="B", folder="Work")
        response = self.client.get(reverse("home"))
        folders = response.context["folders"]
        work = next(f for f in folders if f["name"] == "Work")
        self.assertEqual(work["color"], "blue")
        self.assertEqual(work["count"], 2)

    def test_home_lists_empty_folder_with_zero_count(self):
        Folder.objects.create(user=self.user, name="Empty")
        response = self.client.get(reverse("home"))
        folders = response.context["folders"]
        empty = next(f for f in folders if f["name"] == "Empty")
        self.assertEqual(empty["count"], 0)

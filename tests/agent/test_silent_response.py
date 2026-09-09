"""Tests for the opt-in ``[[silent]]`` silence feature (agent side).

Contract under test:
- ``is_silent_response`` matches ONLY the exact marker (anchored equality).
- ``silent_allowed`` defaults to False (opt-in via ``agent.allow_silent_responses``).
- ``recover_empty_response`` ends the turn immediately on marker+allowed: no
  retries, no fallback, no ``(empty)`` — and past context is untouched.
- ``finish_text_response`` keeps the marker as final on marker+allowed, bypassing
  every continuation branch (ack/stall, length-join, dropped-tool-call).
- Marker WITHOUT the flag is ordinary text: the normal ladder/guards apply.
"""

from types import SimpleNamespace

import pytest

from agent import empty_response_guard as guard
from agent.turn_empty_response import recover_empty_response


def _agent(**overrides):
    base = dict(
        model="test-model",
        provider="test-provider",
        api_mode="chat_completions",
        _allow_silent_responses=False,
        _empty_content_retries=0,
        _thinking_prefill_retries=0,
        _fallback_chain=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _assistant(content):
    return SimpleNamespace(
        content=content,
        tool_calls=None,
        reasoning=None,
        reasoning_content=None,
        reasoning_details=None,
    )


class TestMarkerMatch:
    @pytest.mark.parametrize("content", ["[[silent]]", "  [[silent]]  ", "[[silent]]\n", "[[silent]] "])
    def test_exact_marker_matches(self, content):
        assert guard.is_silent_response(content) is True

    @pytest.mark.parametrize(
        "content",
        [
            "[[silent]] please ignore",
            "note: [[silent]]",
            "[[Silent]]",  # case-sensitive: not the signal
            "[silent]",
            "[[silent]",
            "(empty)",
            "",
            "   ",
            None,
            42,
        ],
    )
    def test_non_exact_content_does_not_match(self, content):
        assert guard.is_silent_response(content) is False

    def test_silent_allowed_defaults_to_false(self):
        assert guard.silent_allowed(SimpleNamespace()) is False
        assert guard.silent_allowed(_agent()) is False

    def test_silent_allowed_when_flag_set(self):
        assert guard.silent_allowed(_agent(_allow_silent_responses=True)) is True


class TestRecoverEmptyResponse:
    def _call(self, agent, content):
        return recover_empty_response(
            agent,
            _assistant(content),
            SimpleNamespace(usage=None),
            "stop",
            final_response=content,
            messages=[],
            api_messages=[],
            conversation_history=[],
            active_system_prompt="sys",
            api_call_count=1,
            turn_exit_reason="test",
            preflight_compression_blocked=False,
        )

    def test_marker_allowed_breaks_before_retry_ladder(self):
        agent = _agent(
            _allow_silent_responses=True,
            _fallback_chain=["fallback-model"],  # must NOT activate
        )
        agent._try_activate_fallback = lambda: (_ for _ in ()).throw(
            AssertionError("fallback must not activate on silence")
        )
        messages = []
        verdict = recover_empty_response(
            agent,
            _assistant("[[silent]]"),
            SimpleNamespace(usage=None),
            "stop",
            final_response="[[silent]]",
            messages=messages,
            api_messages=[],
            conversation_history=[],
            active_system_prompt="sys",
            api_call_count=1,
            turn_exit_reason="test",
            preflight_compression_blocked=False,
        )
        assert verdict.action == "break"
        assert verdict.final_response == "[[silent]]"
        assert verdict.turn_exit_reason == "silent_response"
        assert agent._empty_content_retries == 0  # no retry burned
        assert messages == []  # past context untouched

    def test_padded_marker_allowed_is_normalized(self):
        agent = _agent(_allow_silent_responses=True)
        verdict = self._call(agent, "  [[silent]]\n")
        assert verdict.action == "break"
        assert verdict.final_response == "[[silent]]"

    def test_marker_without_flag_runs_normal_ladder(self):
        """Flag off: the marker is ordinary non-empty text, so the normal path
        applies — here retries are exhausted with no fallback, yielding ``(empty)``."""
        agent = _agent(
            _allow_silent_responses=False,
            _empty_content_retries=99,
            _has_content_after_think_block=lambda c: bool((c or "").strip()),
            _strip_think_blocks=lambda s: s,
            _flush_status_buffer=lambda: None,
            _extract_reasoning=lambda m: "",
            _drop_trailing_empty_response_scaffolding=lambda msgs: None,
            _build_assistant_message=lambda m, fr: {"role": "assistant", "content": ""},
            _emit_status=lambda *a, **k: None,
        )
        verdict = self._call(agent, "[[silent]]")
        assert verdict.action == "break"
        assert verdict.final_response == "(empty)"  # NOT kept as silence


class TestFinishTextResponse:
    def _agent(self, allowed):
        return SimpleNamespace(
            model="test-model",
            provider="test-provider",
            api_mode="chat_completions",
            _allow_silent_responses=allowed,
            _mute_post_response=True,  # must be cleared by the path
            _empty_content_retries=3,
            _thinking_prefill_retries=2,
            _dropped_toolcall_retries=0,
            _stall_guards=True,
            _intent_ack_continuation="off",
            valid_tool_names=["some_tool"],
            quiet_mode=True,
            session_id="test-session",
            _has_content_after_think_block=lambda c: bool((c or "").strip()),
            _strip_think_blocks=lambda s: s,
            _looks_like_codex_intermediate_ack=lambda **kw: True,
            _build_assistant_message=lambda m, fr: {
                "role": "assistant",
                "content": m.content if isinstance(m.content, str) else "",
            },
            _flush_messages_to_session_db=lambda *a: None,
            _safe_print=lambda *a, **k: None,
            _emit_pending_fallback_notice=lambda: None,
            _clear_status_buffer=lambda: None,
            _emit_interim_assistant_message=lambda m: None,
            _emit_status=lambda *a, **k: None,
        )

    def _call(self, agent, messages):
        from agent.turn_final_response import finish_text_response

        return finish_text_response(
            agent,
            assistant_message=_assistant("[[silent]]"),
            response=SimpleNamespace(),
            finish_reason="stop",
            messages=messages,
            api_messages=[],
            conversation_history=[],
            api_call_count=1,
            user_message="hi",
            active_system_prompt="sys",
            final_response="[[silent]]",
            _turn_exit_reason="test",
            _preflight_compression_blocked=False,
            codex_ack_continuations=0,
            truncated_response_parts=[],
            length_continue_retries=0,
            _pending_verification_response=None,
            _pending_verification_response_previewed=False,
        )

    def test_marker_allowed_kept_as_final(self, monkeypatch):
        """Allowed marker ends the turn with exactly one assistant row — strict role
        alternation, no ack/stall continuation despite the ack stub matching."""
        from agent.turn_final_response import apply_stop_gates  # noqa: F401 (import check)

        monkeypatch.setattr(
            "agent.turn_final_response.apply_stop_gates",
            lambda *a, **k: SimpleNamespace(
                continue_turn=False,
                pending_verification_response=None,
                pending_verification_response_previewed=False,
            ),
        )
        agent = self._agent(allowed=True)
        messages = []
        verdict = self._call(agent, messages)
        assert verdict.action == "break"
        assert verdict.final_response == "[[silent]]"
        assert verdict._turn_exit_reason == "silent_response"
        # The ack stub returns True — a non-silent reply would have continued.
        assert len(messages) == 1  # strict alternation: exactly one assistant row
        assert messages[0]["role"] == "assistant"
        assert messages[0]["content"] == "[[silent]]"
        assert agent._mute_post_response is False
        assert agent._empty_content_retries == 0

    def test_marker_without_flag_is_ordinary_text(self, monkeypatch):
        """Flag off: the marker goes through the normal guards (here the matching
        ack stub forces a continuation, proving no silent bypass)."""
        monkeypatch.setattr(
            "agent.turn_final_response.apply_stop_gates",
            lambda *a, **k: SimpleNamespace(
                continue_turn=False,
                pending_verification_response=None,
                pending_verification_response_previewed=False,
            ),
        )
        monkeypatch.setattr(
            "agent.agent_runtime_helpers.trailing_continue_intent", lambda text: True
        )
        agent = self._agent(allowed=False)
        verdict = self._call(agent, [])
        assert verdict.action == "continue"
        assert verdict.final_response is None  # continuation, not a silent final

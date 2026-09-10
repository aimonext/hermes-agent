"""session-model-switch — per-session private/normal model router.

Hooks ``pre_gateway_dispatch`` (gateway ingress, before auth/session creation)
to intercept trigger phrases and store a **session-scoped** model override
on the GatewayRunner's SessionState — never on global config.yaml.

Flexible triggers (intent-based, Bangla/English mix):
  enter private (any of, case-insensitive, punctuation-tolerant):
    - "/private"  (exact slash)
    - "aso ektu private chat kori" (+ variations: "aso private e jai",
      "cholo ekanto e kotha boli", "let's go private", "private chat kori",
      "ektu adult chat kori", "private e jai", "ektu private", etc.)
    Detection = keyword-intent: (private + chat/kotha/kori/jai/aso/cholo/ektu)
      OR strong-alone: ekanto/ekant/intimate/nsfw
      OR adult+chat/kori
  exit private (flexible):
    - "/normal"
    - "private sesh" / "private shesh" / "private off/close/stop/bondho"
    - "normal e fire aso" / "back to normal" / "normal e jai" / etc.

Effects:
  enter -> gateway._session_state(key).conversation.model_override = {
             "model": "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
             "provider": "openrouter",
           }
  exit  -> clear override (revert to default opencode-free/muse-spark) via None

Policy:
  - Session-scoped only: key = gateway._session_key_for_source(source)
  - No config.yaml mutation, no env writes, no profile inheritance.
  - Evicts cached agent for the session so next turn binds new model.
  - Trigger rewritten to system note so transcript stays clean.
  - LLM intent classifier hook reserved for future (keyword path is primary).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Model constants ───────────────────────────────────────────────────────
PRIVATE_PROVIDER = "openrouter"
PRIVATE_MODEL = "cognitivecomputations/dolphin-mistral-24b-venice-edition:free"
PRIVATE_OVERRIDE: Dict[str, Any] = {
    "model": PRIVATE_MODEL,
    "provider": PRIVATE_PROVIDER,
}
NORMAL_PROVIDER = "opencode-free"
NORMAL_MODEL = "muse-spark"

# ── Normalization ─────────────────────────────────────────────────────────
def _normalize_text(raw: str | None) -> str:
    if not raw:
        return ""
    t = str(raw).strip().lower()
    # zero-width / NBSP, bidi
    t = t.replace("\u00a0", " ").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    # keep letters, numbers, slash; replace punctuation with space except slash
    # preserve slash for /private /normal detection
    t = re.sub(r"[!.,;:?…\"'()\[\]{}—–\-]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

# ── Keyword intent sets ───────────────────────────────────────────────────
# Strong-alone tokens that imply private intent even without "chat"
_STRONG_PRIVATE_ALONE = ("ekanto", "ekant", "intimate", "nsfw", "horny", "sexy", "18+")

# Verbs/nouns that with "private" signal intent
_PRIVATE_CHAT_VERBS = (
    "chat", "kotha", "kothaboli", "kotha boli",
    "golpo", "gopon", "gopone",
    "kori", "korbo", "kore", "korchi",
    "jai", "jao", "jabo", "jawa", "jaze",
    "aso", "asoo", "aso", "asho",
    "cholo", "chalo", "cholen",
    "ektu", "ekto",
    "talk", "mode", "session", "room",
    "go", "let", "lets", "let's",
    "adult",
)

_EXIT_PRIVATE_TERMINATORS = ("sesh", "shesh", "sheshh", "ses", "off", "close", "bondho", "khatam", "end", "exit", "stop", "done", "ses koro", "sesh koro")
_EXIT_NORMAL_SIGNALS = ("normal", "back to normal", "normal e", "fire aso", "fire ashi", "fire gelam", "fire jai", "fire jabo", "normal mode", "normal chat")

def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(n in haystack for n in needles)

def _is_enter_intent(t: str) -> bool:
    """Flexible ENTER intent classifier (keyword-based, no LLM needed)."""
    if not t:
        return False
    # Exact slash commands (normalized keeps slash)
    if t.strip() == "/private" or t.strip().startswith("/private "):
        return True
    # Strong-alone: ekanto / intimate / nsfw etc. (avoid short "adult" alone)
    if _contains_any(t, _STRONG_PRIVATE_ALONE):
        return True
    # "adult chat/kori/kotha" pattern (adult alone is too ambiguous, require chat verb)
    if "adult" in t and _contains_any(t, ("chat", "kori", "korbo", "kotha", "golpo", "talk")):
        return True
    # "private" + any chat verb → enter
    if "private" in t and _contains_any(t, _PRIVATE_CHAT_VERBS):
        return True
    # Explicit bigrams that users actually say
    bigrams = (
        "private e jai", "private e jabo", "private e jai",
        "private chat", "private kori", "private korbo",
        "private kotha", "private golpo", "private mode",
        "private e kotha", "private e chat",
        "go private", "lets go private", "let's go private",
        "ekanto e kotha", "ekanto kotha", "ekanto chat",
        "ektu private", "ektu adult",
    )
    if _contains_any(t, bigrams):
        return True
    # LLM fallback placeholder — if keyword path missed but LLM says private intent,
    # caller can invoke _llm_classify_intent(t). Kept separate so hook stays sync.
    return False

def _is_exit_intent(t: str) -> bool:
    """Flexible EXIT intent classifier."""
    if not t:
        return False
    if t.strip() == "/normal" or t.strip().startswith("/normal "):
        return True
    if "back to normal" in t:
        return True
    # private + terminator: "private sesh", "private off", "private bondho" etc.
    if "private" in t and _contains_any(t, _EXIT_PRIVATE_TERMINATORS):
        return True
    # "sesh" alone is ambiguous — only if prior session is private; but we treat
    # bare "sesh"/"shesh" as exit only when it also contains private/normal context
    # to avoid false exit on "kaj sesh". So require private/normal co-signal.
    # "normal e fire aso" family
    if "normal" in t and _contains_any(t, ("fire", "back", "return", "aso", "ashi", "jabo", "jai", "e fire", "e aso", "mode")):
        return True
    # "normal chat", "normal mode e fire"
    if "normal" in t and len(t.split()) <= 5:  # short "normal e jai" etc.
        # bare "normal" with small context = exit
        return True
    # explicit close phrases
    if _contains_any(t, ("close private", "exit private", "stop private", "off private", "private off", "private close")):
        return True
    return False

def classify_trigger(text: str | None) -> Optional[str]:
    """Return 'enter' | 'exit' | None. Exit checked first so 'private sesh' doesn't hit enter."""
    t = _normalize_text(text)
    if not t:
        return None
    # Exit before enter — "private sesh" contains "private" but is exit
    if _is_exit_intent(t):
        return "exit"
    if _is_enter_intent(t):
        return "enter"
    # Optional LLM intent classifier (async future) — sync hook can't await LLM,
    # so we keep keyword path authoritative and log ambiguous case.
    # Uncomment when ctx.llm is available in hook scope:
    #   llm_verdict = _llm_classify_intent(t)  # must be sync-safe or cached
    return None

def _llm_classify_intent(text: str) -> Optional[str]:
    """Reserved LLM-based intent classifier (not used in sync pre_gateway_dispatch).

    Future implementation: call ctx.llm with a tiny intent prompt:
      "Classify as enter_private / exit_private / none for: {text}"
    Must be non-blocking, cached, and fail-open to None.

    Keeping the stub here documents the extension point the user requested.
    """
    # Example (when PluginContext is available):
    #   resp = ctx.llm.chat([{"role":"user","content": prompt}], max_tokens=10)
    #   label = resp.strip().lower()
    #   return "enter" if "enter" in label else "exit" if "exit" in label else None
    return None

# ── Session-key helpers ───────────────────────────────────────────────────
def _session_key_for(gateway: Any, source: Any) -> Optional[str]:
    """Best-effort session key mirroring GatewayRunner._session_key_for_source."""
    try:
        if hasattr(gateway, "_normalize_source_for_session_key"):
            source = gateway._normalize_source_for_session_key(source)
    except Exception:
        pass
    try:
        if hasattr(gateway, "_session_key_for_source"):
            k = gateway._session_key_for_source(source)
            if isinstance(k, str) and k:
                return k
    except Exception:
        logger.debug("session-model-switch: _session_key_for_source failed", exc_info=True)
    try:
        from gateway.session import build_session_key
        cfg = getattr(gateway, "config", None)
        return build_session_key(
            source,
            group_sessions_per_user=getattr(cfg, "group_sessions_per_user", True),
            thread_sessions_per_user=getattr(cfg, "thread_sessions_per_user", False),
            profile=getattr(source, "profile", None),
        )
    except Exception:
        logger.debug("session-model-switch: fallback build_session_key failed", exc_info=True)
        return None

def _apply_override(gateway: Any, session_key: str, override: Optional[Dict[str, Any]]) -> None:
    """Set/clear gateway SessionState.conversation.model_override for session_key."""
    if not session_key:
        return
    try:
        if hasattr(gateway, "_session_state"):
            state = gateway._session_state(session_key)
            state.conversation.model_override = override
            if override is not None:
                state.conversation.one_turn_restore = None
            logger.info("session-model-switch: %s model_override for %s",
                        "set" if override else "cleared", session_key)
        elif hasattr(gateway, "_session_model_overrides"):
            if override is None:
                gateway._session_model_overrides.pop(session_key, None)
            else:
                gateway._session_model_overrides[session_key] = override
    except Exception:
        logger.warning("session-model-switch: failed to apply override for %s", session_key, exc_info=True)

def _evict_agent_cache(gateway: Any, session_key: str) -> None:
    try:
        if hasattr(gateway, "_evict_cached_agent"):
            gateway._evict_cached_agent(session_key)
        elif hasattr(gateway, "_agent_cache"):
            gateway._agent_cache.pop(session_key, None)
    except Exception:
        logger.debug("session-model-switch: evict cache failed for %s", session_key, exc_info=True)

# ── Hook ──────────────────────────────────────────────────────────────────
def on_pre_gateway_dispatch(
    event: Any = None,
    gateway: Any = None,
    session_store: Any = None,
    **kwargs: Any,
):
    """pre_gateway_dispatch hook — flexible session-scoped private/normal switch."""
    try:
        text = getattr(event, "text", None)
        if text is None and isinstance(event, dict):
            text = event.get("text")
        kind = classify_trigger(text)
        if kind is None:
            return None

        source = getattr(event, "source", None)
        if source is None and isinstance(event, dict):
            source = event.get("source")
        if source is None or gateway is None:
            logger.debug("session-model-switch: no source/gateway for trigger %s", kind)
            return None

        session_key = _session_key_for(gateway, source)
        if not session_key:
            logger.warning("session-model-switch: could not derive session_key for trigger %s", kind)
            return None

        # Optional PluginState mirror (best-effort, survives gateway restart)
        try:
            from hermes_cli.plugins_state import PluginState
            ps = PluginState("session-model-switch", "")
            ps.set(f"sessions.{session_key}.private", kind == "enter")  # type: ignore
        except Exception:
            pass

        if kind == "enter":
            _apply_override(gateway, session_key, dict(PRIVATE_OVERRIDE))
            _evict_agent_cache(gateway, session_key)
            logger.info("session-model-switch: ENTER private for %s (dolphin) via %r", session_key, _normalize_text(text)[:80])
            return {
                "action": "rewrite",
                "text": (
                    "[SYSTEM NOTE: Private mode activated for this session only. "
                    "You are now running on openrouter/cognitivecomputations/dolphin-mistral-24b-venice-edition:free. "
                    "Respond warmly: 'Private mode on — I'm all yours here. 🖤' then continue naturally. "
                    "This override is session-scoped; other sessions stay on opencode-free/muse-spark.]"
                ),
            }
        else:  # exit
            _apply_override(gateway, session_key, None)
            _evict_agent_cache(gateway, session_key)
            logger.info("session-model-switch: EXIT private for %s (revert to muse-spark) via %r", session_key, _normalize_text(text)[:80])
            return {
                "action": "rewrite",
                "text": (
                    "[SYSTEM NOTE: Private mode ended for this session. Reverted to opencode-free/muse-spark. "
                    "Respond briefly: 'Back to normal — private sesh closed. 🙂' ]"
                ),
            }
    except Exception as exc:
        logger.warning("session-model-switch hook error: %s", exc, exc_info=True)
        return None

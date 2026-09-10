# session-model-switch — Implementation Plan

**Goal:** Per-session model switching for private adult chat without global config mutation or separate profile. Must be session-scoped, flexible triggers, reversible.

## 1. Triggers (flexible intent, not exact phrase)
User will phrase entry/exit many ways in Bangla/English mix. Use keyword-intent classifier (switcher.py `classify_trigger`).

**Enter private** (any → sets override):
- `/private` (canonical slash)
- Bangla/English variants: `aso ektu private chat kori`, `aso private e jai`, `cholo ekanto e kotha boli`, `let's go private`, `private chat kori`, `ektu adult chat kori`, `private e jai`, `ektu private`, `private kori`, `gopon chat`, etc.
- Rule: `private` + any chat verb (`chat/kotha/kori/jai/aso/cholo/ektu/talk/mode/go`) OR strong-alone `ekanto/ekant/intimate/nsfw/horny/sexy` OR `adult+chat/kori`

**Exit private** (any → clears override):
- `/normal` (canonical)
- `private sesh` / `private shesh` / `private off|close|stop|bondho|khatam|end`
- `normal e fire aso` / `back to normal` / `normal e jai` / `normal mode` / bare `normal` (short)
- Exit checked **before** enter so `private sesh` doesn't misfire as enter.

Punctuation/whitespace/case/bidi tolerant; `/private` & `/normal` win exactly.

**Future LLM gate:** `_llm_classify_intent()` stub reserved — keyword path is sync-safe for `pre_gateway_dispatch` (policy gate, not timeout-bounded). LLM can be added as cached non-blocking supplement when `ctx.llm` is available in hook scope; must fail-open.

## 2. Architecture

```
User message → gateway/run_inbound.py _hm_pre_gateway_dispatch_hook()
                → PluginManager.invoke_hook("pre_gateway_dispatch", event, gateway, session_store)
                  → switcher.on_pre_gateway_dispatch()
                    → classify_trigger(text) → enter/exit/none
                    → _session_key_for(gateway, source)  # honors _normalize_source_for_session_key + multiplex
                    → _apply_override(gateway, key, PRIVATE_OVERRIDE|None)
                    → _evict_agent_cache(gateway, key)
                    → PluginState mirror sessions.<key>.private bool (best-effort, survives restart)
                    → return {"action":"rewrite","text": SYSTEM NOTE} | None
                → gateway either rewrites event.text or drops/permits
              → _resolve_session_agent_runtime() reads SessionState.conversation.model_override
              → _resolve_turn_agent_config() builds route
```

**Session-scoped guarantee:**
- `key = gateway._session_key_for_source(source)` (with `_normalize_source_for_session_key` for Telegram forum topics). Never `~/.hermes/config.yaml` mutation (check `cli.py` no `save_config`).
- `GatewayRunner._session_state(key).conversation.model_override` is authoritative. `_peek_session_state` on next turn in `run_turn.py _resolve_session_agent_runtime` consumes it. `_evict_cached_agent(key)` forces rebind so prompt-cache prefix resets.
- `PluginState("session-model-switch").path = ~/.hermes/plugin-data/agent-plugin-session-model-switch-*/state.json` mirrors `sessions.<key>.private` for cold-start supplement. Gateway state wins on hit.

## 3. Model mapping
- **Private:** `openrouter/cognitivecomputations/dolphin-mistral-24b-venice-edition:free` — override `{"provider":"openrouter","model":"cognitivecomputations/dolphin-mistral-24b-venice-edition:free"}` (no api_key — resolved via existing openrouter credentials; avoids leaking secrets into override).
- **Normal:** clear override → fallback to global `model.default = opencode-free/muse-spark` (or whatever `config.yaml` sets). No explicit normal override needed; clearing is the revert.

## 4. File layout
```
~/.hermes/plugins/session-model-switch/
  plugin.yaml   # manifest v2, provides_hooks: [pre_gateway_dispatch]
  __init__.py   # register(ctx) → ctx.register_hook(...)
  switcher.py   # classifier + session-key helpers + hook
  PLAN.md       # this plan
  README.md     # user guide (Bangla + English triggers)
```

## 5. Validation (do not push)
```bash
python3 -c "from switcher import classify_trigger; assert classify_trigger('/private')=='enter'; assert classify_trigger('aso private e jai')=='enter'; assert classify_trigger('cholo ekanto e kotha boli')=='enter'; assert classify_trigger('private sesh')=='exit'; assert classify_trigger('normal e fire aso')=='exit'; print('classifier ok')"
hermes plugins doctor ~/.hermes/plugins/session-model-switch --ci
hermes plugins list | grep session-model-switch
python3 -m py_compile ~/.hermes/plugins/session-model-switch/__init__.py ~/.hermes/plugins/session-model-switch/switcher.py
```

## 6. Edge cases & safety
- Bare `private` alone does NOT trigger (needs verb) — prevents accidental fires mid-conversation.
- Bare `sesh` alone does NOT exit — requires `private`/`normal` co-signal.
- `pre_gateway_dispatch` is a policy gate: not timeout-bounded, runs synchronously; handler is short (no I/O, no LLM await) so never wedges dispatch.
- Hook never crashes dispatch — all paths wrapped in try/except returning None.
- Multiplex profiles: session key includes profile namespace via gateway helper.
- `/new` / auto-reset / expiry: `ConversationState.clear()` wipes `model_override` — private mode correctly ends at conversation boundary. PluginState mirror can rehydrate if needed.
- Ayesha (ayesha profile) owns `git push` — this plugin does not push; file creation + doctor validation only.

## 7. Next steps (post-skeleton)
- Add LLM classifier when gateway exposes `ctx.llm` to hooks (non-blocking, cached 5m).
- Optional `/private` & `/normal` as real slash commands in COMMAND_REGISTRY for help/menu discovery.
- Dashboard toggle for private mode per session.

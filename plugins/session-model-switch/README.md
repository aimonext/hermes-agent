# session-model-switch

Per-session private model switch — **no global config, no separate profile**.

Say any of these in a DM/group thread → that session flips to uncensored Dolphin; other sessions stay on `muse-spark`.

**Enter private (flexible):** `/private`, `aso ektu private chat kori`, `aso private e jai`, `cholo ekanto e kotha boli`, `let's go private`, `private chat kori`, `ektu adult chat kori`, `ektu private`, `ekanto e kotha`, `intimate chat`, etc.

**Exit private (flexible):** `/normal`, `private sesh` / `shesh`, `private off/close/bondho`, `normal e fire aso`, `back to normal`, `normal e jai`.

## How it works
`pre_gateway_dispatch` hook (gateway ingress) classifies intent via keywords (no LLM blocking), derives `session_key` via `gateway._session_key_for_source` (Telegram topic-aware, profile-namespaced), sets `gateway._session_state(key).conversation.model_override = {provider:"openrouter", model:"cognitivecomputations/dolphin-mistral-24b-venice-edition:free"}` and evicts cached agent. Exit clears override. PluginState mirrors mode for restart survival.

## Security
Session-scoped only. No `config.yaml` write, no env leak. `/new` or expiry ends private mode.

## Validate
```bash
hermes plugins doctor ~/.hermes/plugins/session-model-switch --ci
```
Ask Ayesha (`ayesha` profile) to push.

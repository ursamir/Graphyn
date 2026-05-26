# Group Review Index — 8: Platform Infra

**Files reviewed:** 5  
**Total findings:** 12 (CRITICAL: 0 | HIGH: 4 | MEDIUM: 5 | LOW: 3)  
**Date:** 2026-05-26

---

## File Summaries

| File | Overall Risk | Silent Failures | Top Risk |
|---|---|---|---|
| config.md | MEDIUM | 2 | `_env()` silently treats whitespace-only `GRAPHYN_API_TOKEN` as no-auth, bypassing authentication. |
| validation.md | HIGH | 1 | `validate_pipeline()` rejects all configs that omit `pipeline.seed`, breaking any pipeline that doesn't explicitly set a seed value. |
| webhook.md | HIGH | 1 | DNS rebinding SSRF bypass: `_is_private_host()` and `httpx` use separate DNS resolution paths, leaving a race window where the check passes but the connection goes to an internal host. |
| errors.md | LOW | 0 | None |
| hash.md | HIGH | 2 | `default=str` silently converts non-JSON-serializable objects with memory-address-based `str()` reprs, producing hashes that are NOT stable across process restarts. |

---

## Priority Findings (CRITICAL and HIGH only)

**[HIGH] validation.md — `validate_pipeline` — Rejects all pipeline configs that omit `pipeline.seed` (treats absent seed as invalid integer), breaking any graph that doesn't set an explicit seed.**

**[HIGH] webhook.md — `WebhookService._send` / `_is_private_host` — DNS rebinding SSRF bypass: `socket.gethostbyname()` check and `httpx` DNS resolution are independent, leaving a race window for an attacker to redirect the connection to an internal host after the check passes.**

**[HIGH] webhook.md — `WebhookService.notify` / `WebhookService._send` — Daemon thread is killed on process exit mid-POST, causing partial/truncated webhook delivery during graceful shutdown.**

**[HIGH] hash.md — `stable_hash` — `default=str` silently converts non-JSON-serializable objects (including those with memory-address `str()` reprs) to strings, producing hashes that are NOT stable across process restarts, violating the function's core stability guarantee.**

---

## Most Dangerous File

**validation.md** — `validate_pipeline()` contains a logic error that rejects every pipeline config that omits `pipeline.seed` (the majority of real-world configs), making the validator effectively broken for standard use.

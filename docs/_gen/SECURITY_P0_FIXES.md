# Security P0 fixes (Claude Code review §6 #1–4)

Branch: `cursor/usecase-plugins-workflows`  
Scope: four security P0s only (stubs / fcntl / distributed zombie deferred).

## 1. Path traversal via unvalidated project name
- **Files:** `app/domain/project_manager.py`, `app/api/routers/ship.py`
- **Change:** `_require_project()` now calls `_validate_name()` and rejects resolved paths outside `BASE`. `ship.py` maps `ValueError` → HTTP 422.
- **Tests:** `unit_test/core/test_project_name_traversal.py`, API smoke in `test_security_p0_api.py`

## 2. Plugin source allowlist bypass
- **Files:** `app/core/config.py`, `app/core/plugins/installer.py`, `app/api/routers/plugins.py`
- **Change:** Remote detection is scheme-case-insensitive and covers any `scheme://` (incl. `git://` / `ssh://`). Unsupported schemes fail closed. Installer normalizes then allowlist-checks before clone/download.
- **Tests:** `unit_test/core/test_plugin_allowlist_bypass.py`

## 3. Webhook URL returned in plaintext
- **Files:** `app/core/egress.py`, `app/core/webhook.py`, `app/api/routers/system.py`, `app/core/audit.py`
- **Change:** API get/put/test return redacted scheme://host/*** (`redact_webhook_url_for_api`); `public_config()` / `url_configured`; audit `resource_id` redacted on write and on `list_audit` read for legacy rows. Delivery still uses raw URL from disk via `load()`.
- **Tests:** `unit_test/core/test_webhook_url_redaction.py`, `unit_test/api/test_security_p0_api.py`

## 4. Plugin-install errors leak URL credentials
- **Files:** `app/core/plugins/installer.py`, `app/api/routers/plugins.py`
- **Change:** `redact_url_userinfo()` strips `user:pass@` from URLs and embedded error strings; installer errors, job-status, and HTTP error bodies use it.
- **Tests:** covered in `test_plugin_allowlist_bypass.py`

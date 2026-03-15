---
description: "Use when working on Podvoice to preserve local-first, reproducible, and open-source design principles."
applyTo: "**/*.{py,md,toml,sh,ps1,yml,yaml}"
---

# Podvoice Core Principles

Podvoice is intentionally local-first and developer-focused. Keep all changes aligned with these rules.

## Non-negotiable rules

1. Keep Podvoice local-first.
- Do not introduce required cloud APIs, hosted inference, subscriptions, or vendor lock-in.
- Prefer offline execution paths by default.

2. Keep workflows reproducible.
- Favor deterministic behavior and script-based automation.
- Prefer pinned dependencies and explicit configuration over hidden defaults.

3. Keep the project small and hackable.
- Prefer simple, understandable implementations.
- Avoid unnecessary architecture layers, large refactors, or heavy abstractions unless explicitly requested.

4. Keep dependencies practical and open.
- Prefer stable open-source components.
- Do not add proprietary service dependencies unless the user explicitly asks for them.

5. Preserve the script input contract.
- Renderable scripts must use Podvoice speaker blocks: ``[Speaker | emotion]``.
- Treat free-form Markdown prose as non-renderable input until converted.

6. Keep emotion semantics explicit.
- Emotion is metadata in current behavior.
- It may affect parse/merge boundaries and cache keys.
- It is not a guaranteed prosody or style control unless explicitly implemented.

7. Protect current performance defaults.
- Preserve in-memory synthesis and stitching flow.
- Preserve deterministic segment caching.
- Preserve adjacent same-speaker merge optimization.

8. Use evidence-first performance changes.
- For performance-related changes, run and compare benchmark output.
- For parser/cache behavior changes, add or update regression tests.

9. Local-first exceptions must be explicit.
- Cloud or proprietary integrations are allowed only when explicitly requested.
- Such integrations must remain optional and disabled by default.

## Change-review checklist

Before finalizing any change, verify:
- Does this keep the default path fully local?
- Does this improve or preserve reproducibility?
- Is this solution simple enough for contributors to read and modify?
- Does this avoid paid or proprietary platform requirements?
- Does the change preserve the speaker-block input contract?
- Are emotion expectations clearly documented in code/docs?
- If this is a performance change, is benchmark evidence included?
- If parser/cache logic changed, are regression tests updated?

## Scope note

These rules are default project policy. If a request conflicts with them, call out the conflict and ask for explicit approval before proceeding.

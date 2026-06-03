"""Centralized AI service for HeyKiki.

The single, shared LLM layer (per the "build one shared LLM service, not
per-feature calls" directive). Consumers:
  - the in-app Kiki copilot (app/services/copilot/),
  - the deferred classifiers (emergency-flag detection, employee auto-assign).

Phase 0 — BUILD-ONLY: ships inert until OPENAI_API_KEY is set (see ``client``).
"""

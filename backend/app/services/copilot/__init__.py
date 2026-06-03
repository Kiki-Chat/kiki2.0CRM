"""The in-app Kiki copilot — agentic loop + tool registry over the centralized
AI service (app/services/ai). Phase 0/1: read tools + the confirmed-write flow.

Ships behind ``settings.copilot_enabled`` (off) — the router in
app/api/routes/copilot.py is only mounted when the flag is on.
"""

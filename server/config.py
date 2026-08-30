"""
Signal Bridge Remote — Server Configuration

All settings are loaded from environment variables with sensible defaults.
In production, set SB_SECRET_KEY to a random 64-char string.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # Load .env file before reading any env vars

# ── Server ──────────────────────────────────────────────────────────────
HOST = os.getenv("SB_HOST", "0.0.0.0")
PORT = int(os.getenv("SB_PORT", "8420"))
SECRET_KEY = os.getenv("SB_SECRET_KEY", "")  # MUST be set in production
CORS_ORIGINS = os.getenv("SB_CORS_ORIGINS", "*").split(",")

# ── Auth ────────────────────────────────────────────────────────────────
TOKEN_EXPIRY_HOURS = int(os.getenv("SB_TOKEN_EXPIRY_HOURS", "168"))  # 1 week
REGISTRATION_OPEN = os.getenv("SB_REGISTRATION_OPEN", "true").lower() == "true"
REQUIRE_MCP_AUTH = os.getenv("SB_REQUIRE_MCP_AUTH", "false").lower() == "true"
# Optional single-user self-hosting mode. The same token authenticates the
# Android phone WebSocket and MCP HTTP requests. Leave blank to disable.
STATIC_BEARER_TOKEN = os.getenv("SB_STATIC_BEARER_TOKEN", "").strip()

# ── Rate Limiting ───────────────────────────────────────────────────────
# Format: "count/period" — e.g. "5/minute", "100/hour"
RATE_LIMIT_AUTH = os.getenv("SB_RATE_LIMIT_AUTH", "5/minute")
RATE_LIMIT_COMMANDS = os.getenv("SB_RATE_LIMIT_COMMANDS", "120/minute")
RATE_LIMIT_GLOBAL = os.getenv("SB_RATE_LIMIT_GLOBAL", "300/minute")
MAX_WS_PER_IP = int(os.getenv("SB_MAX_WS_PER_IP", "3"))
BAN_THRESHOLD = int(os.getenv("SB_BAN_THRESHOLD", "20"))
BAN_DURATION_MINUTES = int(os.getenv("SB_BAN_DURATION_MINUTES", "30"))

# ── Safety ──────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL_S = float(os.getenv("SB_HEARTBEAT_INTERVAL", "2.0"))
HEARTBEAT_TIMEOUT_S = float(os.getenv("SB_HEARTBEAT_TIMEOUT", "6.0"))

# ── Governor (session intensity limiter) ───────────────────────────────
# Heat accumulates based on intensity × time, dissipates when idle.
# Cooldown triggers when heat reaches threshold, exits at the floor.
GOVERNOR_ENABLED = os.getenv("SB_GOVERNOR_ENABLED", "true").lower() == "true"
GOVERNOR_HEAT_RATE = float(os.getenv("SB_GOVERNOR_HEAT_RATE", "3.0"))        # heat units/sec at intensity=1.0
GOVERNOR_COOL_RATE = float(os.getenv("SB_GOVERNOR_COOL_RATE", "2.0"))        # heat units/sec dissipation when idle
GOVERNOR_COOLDOWN_THRESHOLD = float(os.getenv("SB_GOVERNOR_COOLDOWN_ENTER", "90.0"))  # heat% to trigger cooldown
GOVERNOR_COOLDOWN_EXIT = float(os.getenv("SB_GOVERNOR_COOLDOWN_EXIT", "30.0"))        # heat% to exit cooldown
GOVERNOR_COOLDOWN_DURATION = float(os.getenv("SB_GOVERNOR_COOLDOWN_DURATION", "30.0"))  # min seconds in cooldown

# ── Pattern Library ─────────────────────────────────────────────────────
# Per-user JSON storage for saved custom waveforms (pattern_store.py).
PATTERNS_DIR = os.getenv("SB_PATTERNS_DIR", str(Path(__file__).parent / "data" / "patterns"))

# ── Database ────────────────────────────────────────────────────────────
DB_PATH = os.getenv("SB_DB_PATH", str(Path(__file__).parent / "signal_bridge.db"))


def validate():
    """Check that critical config is set. Call on startup."""
    if not SECRET_KEY:
        raise RuntimeError(
            "SB_SECRET_KEY is not set. Generate one with: "
            "python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if STATIC_BEARER_TOKEN and len(STATIC_BEARER_TOKEN) < 32:
        raise RuntimeError(
            "SB_STATIC_BEARER_TOKEN must be at least 32 characters. Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )

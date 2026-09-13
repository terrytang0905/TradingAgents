"""Rate Limiter for API Protection.

Monitors and protects API calls from exceeding rate limits.
Integrated via Hook (PostToolUse) and manual calls in dataflows.
"""

import json
import threading
import time
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from langchain_core.callbacks import BaseCallbackHandler


class RateLimitExceeded(RuntimeError):
    """Raised before a model request when the local quota is exhausted."""


@dataclass
class RateLimitConfig:
    """Rate limit configuration for an API."""
    rpm: int              # Requests per minute
    tpm: int = 0          # Tokens per minute (0 = no limit)
    warning_threshold: float = 0.9  # Warn at 90%
    block_threshold: float = 0.95   # Block at 95%
    cooldown_seconds: float = 60.0  # Wait time when blocked


class RateLimiter:
    """Protect API calls from exceeding rate limits.

    Thread-safe implementation with persistent logging.

    Usage:
        # Before API call
        if not RateLimiter.check_can_call("openai_chat"):
            RateLimiter.wait_if_needed("openai_chat")

        # After API call
        RateLimiter.log_call("openai_chat", tokens=500)

        # Check remaining quota
        remaining = RateLimiter.get_remaining_quota("openai_chat")
    """

    # Rate limit configurations per API type
    LIMITS: Dict[str, RateLimitConfig] = {
        "openai_chat": RateLimitConfig(rpm=500, tpm=200000),
        "openai_embedding": RateLimitConfig(rpm=100),
        "finnhub": RateLimitConfig(rpm=60),
        "yfinance": RateLimitConfig(rpm=2000),
        "google_news": RateLimitConfig(rpm=100),
        "reddit": RateLimitConfig(rpm=60),
        "polygon": RateLimitConfig(rpm=5),
        "alpaca": RateLimitConfig(rpm=200),
    }
    _DEFAULT_LIMITS: Dict[str, RateLimitConfig] = deepcopy(LIMITS)

    # Call history per API type (thread-safe)
    _call_history: Dict[str, List[Dict]] = defaultdict(list)
    _lock = threading.Lock()

    # Log file for API calls
    LOG_DIR = Path(".claude/risk_logs")
    LOG_FILE = LOG_DIR / "api_calls.log"

    @classmethod
    def configure(cls, api_type: str, config: RateLimitConfig):
        """Add or update rate limit configuration.

        Args:
            api_type: API identifier
            config: RateLimitConfig instance
        """
        cls.LIMITS[api_type] = config

    @classmethod
    def reserve_call(cls, api_type: str) -> bool:
        """Atomically reserve one request from the active RPM window."""
        now = time.time()
        with cls._lock:
            config = cls.LIMITS.get(api_type)
            if config is None:
                return False

            recent = [
                call
                for call in cls._call_history.get(api_type, [])
                if now - call["timestamp"] < 60
            ]
            current_rpm = len(recent)
            current_tpm = sum(call["tokens"] for call in recent)
            if current_rpm >= config.rpm * config.block_threshold:
                return False
            if config.tpm > 0 and current_tpm >= config.tpm * config.block_threshold:
                return False

            recent.append({"timestamp": now, "tokens": 0, "metadata": {}})
            cls._call_history[api_type] = recent
            result = {
                "api_type": api_type,
                "rpm": len(recent),
                "rpm_limit": config.rpm,
                "reserved": True,
            }
            cls._persist_log(result)
            return True

    @classmethod
    def log_call(cls, api_type: str, tokens: int = 0,
                 metadata: Dict = None) -> Dict:
        """Log an API call and check rate limits.

        Args:
            api_type: API identifier (e.g., "openai_chat")
            tokens: Tokens consumed (for TPM tracking)
            metadata: Optional additional metadata

        Returns:
            Dict with 'rpm', 'tpm', 'warning', 'blocked' status
        """
        now = time.time()

        with cls._lock:
            # Add call to history
            call_record = {
                "timestamp": now,
                "tokens": tokens,
                "metadata": metadata or {}
            }
            cls._call_history[api_type].append(call_record)

            # Trim history to last minute
            cls._call_history[api_type] = [
                c for c in cls._call_history[api_type]
                if now - c["timestamp"] < 60
            ]

            # Calculate current rates
            current_rpm = len(cls._call_history[api_type])
            current_tpm = sum(c["tokens"] for c in cls._call_history[api_type])

            # Get limits
            config = cls.LIMITS.get(api_type, RateLimitConfig(rpm=1000))
            rpm_limit = config.rpm
            tpm_limit = config.tpm

            # Check thresholds
            rpm_pct = current_rpm / rpm_limit if rpm_limit > 0 else 0
            tpm_pct = current_tpm / tpm_limit if tpm_limit > 0 else 0

            warning = rpm_pct >= config.warning_threshold or tpm_pct >= config.warning_threshold
            blocked = rpm_pct >= config.block_threshold or (
                tpm_limit > 0 and tpm_pct >= config.block_threshold
            )

            result = {
                "api_type": api_type,
                "rpm": current_rpm,
                "rpm_limit": rpm_limit,
                "rpm_pct": rpm_pct,
                "tpm": current_tpm,
                "tpm_limit": tpm_limit,
                "tpm_pct": tpm_pct,
                "warning": warning,
                "blocked": blocked
            }

            # Log warnings/blocks
            if warning:
                msg = (
                    f"⚠️ Rate Limit Warning: {api_type} at "
                    f"RPM:{current_rpm}/{rpm_limit} TPM:{current_tpm}/{tpm_limit}"
                )
                print(msg)

            if blocked:
                msg = f"🚫 Rate Limit Block: {api_type} exceeded threshold"
                print(msg)

            # Persist to log file
            cls._persist_log(result)

            return result

    @classmethod
    def check_can_call(cls, api_type: str) -> bool:
        """Check if an API call is allowed.

        Args:
            api_type: API identifier

        Returns:
            True if call is allowed, False if blocked
        """
        with cls._lock:
            if api_type not in cls._call_history:
                return True

            now = time.time()
            history = cls._call_history[api_type]

            # Trim to last minute
            recent = [c for c in history if now - c["timestamp"] < 60]
            current_rpm = len(recent)

            config = cls.LIMITS.get(api_type, RateLimitConfig(rpm=1000))

            # Check RPM threshold
            if current_rpm >= config.rpm * config.block_threshold:
                return False

            # Check TPM threshold if applicable
            if config.tpm > 0:
                current_tpm = sum(c["tokens"] for c in recent)
                if current_tpm >= config.tpm * config.block_threshold:
                    return False

            return True

    @classmethod
    def wait_if_needed(cls, api_type: str) -> float:
        """Wait if approaching rate limit.

        Args:
            api_type: API identifier

        Returns:
            Seconds waited (0 if no wait needed)
        """
        config = cls.LIMITS.get(api_type, RateLimitConfig(rpm=1000))

        with cls._lock:
            if api_type not in cls._call_history:
                return 0

            now = time.time()
            history = cls._call_history[api_type]

            # Find oldest call in current window
            recent = [c for c in history if now - c["timestamp"] < 60]
            current_rpm = len(recent)
            current_tpm = sum(c["tokens"] for c in recent)

            rpm_blocked = current_rpm >= config.rpm * config.block_threshold
            tpm_blocked = (
                config.tpm > 0
                and current_tpm >= config.tpm * config.block_threshold
            )
            if not rpm_blocked and not tpm_blocked:
                return 0

            # Calculate wait time until oldest call expires
            if recent:
                oldest_timestamp = min(c["timestamp"] for c in recent)
                wait_time = 60 - (now - oldest_timestamp) + 1  # +1 buffer

                if wait_time > 0:
                    print(f"⏳ Rate limit: waiting {wait_time:.1f}s for {api_type}...")
                    time.sleep(wait_time)
                    return wait_time

        return 0

    @classmethod
    def get_remaining_quota(cls, api_type: str) -> Dict[str, int]:
        """Get remaining API quota.

        Args:
            api_type: API identifier

        Returns:
            Dict with 'rpm_remaining', 'tpm_remaining'
        """
        with cls._lock:
            now = time.time()
            history = cls._call_history.get(api_type, [])

            # Trim to last minute
            recent = [c for c in history if now - c["timestamp"] < 60]
            current_rpm = len(recent)
            current_tpm = sum(c["tokens"] for c in recent)

            config = cls.LIMITS.get(api_type, RateLimitConfig(rpm=1000))

            rpm_remaining = max(0, config.rpm - current_rpm)
            # A value of -1 means that the API has no configured TPM limit.
            tpm_remaining = (
                max(0, config.tpm - current_tpm) if config.tpm > 0 else -1
            )

            return {
                "rpm_remaining": rpm_remaining,
                "tpm_remaining": tpm_remaining,
                "rpm_limit": config.rpm,
                "tpm_limit": config.tpm
            }

    @classmethod
    def get_status(cls) -> Dict[str, Dict]:
        """Get status for all configured APIs.

        Returns:
            Dict mapping api_type -> status dict
        """
        status = {}

        for api_type, config in cls.LIMITS.items():
            quota = cls.get_remaining_quota(api_type)
            rpm_pct = 1 - quota["rpm_remaining"] / quota["rpm_limit"]
            tpm_pct = (
                1 - quota["tpm_remaining"] / quota["tpm_limit"]
                if quota["tpm_limit"] > 0
                else 0
            )

            # Determine status color
            if rpm_pct >= config.block_threshold or tpm_pct >= config.block_threshold:
                color = "🔴"
                state = "blocked"
            elif rpm_pct >= config.warning_threshold or tpm_pct >= config.warning_threshold:
                color = "🟡"
                state = "warning"
            else:
                color = "🟢"
                state = "ok"

            status[api_type] = {
                "rpm_current": quota["rpm_limit"] - quota["rpm_remaining"],
                "rpm_limit": quota["rpm_limit"],
                "rpm_remaining": quota["rpm_remaining"],
                "rpm_pct": rpm_pct,
                "tpm_current": (
                    quota["tpm_limit"] - quota["tpm_remaining"]
                    if quota["tpm_limit"] > 0
                    else 0
                ),
                "tpm_limit": quota["tpm_limit"],
                "tpm_remaining": quota["tpm_remaining"],
                "tpm_pct": tpm_pct,
                "status": state,
                "color": color
            }

        return status

    @classmethod
    def reset(cls, api_type: str = None):
        """Reset call history.

        Args:
            api_type: Specific API to reset, or None for all
        """
        with cls._lock:
            if api_type:
                cls._call_history[api_type] = []
            else:
                cls._call_history = defaultdict(list)
                cls.LIMITS = deepcopy(cls._DEFAULT_LIMITS)

    @classmethod
    def _persist_log(cls, result: Dict):
        """Write log entry to file."""
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": time.time(),
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
            **result
        }

        with open(cls.LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")


class RateLimitCallbackHandler(BaseCallbackHandler):
    """Count and enforce real LangChain model requests in the local limiter."""

    raise_error = True

    def __init__(self, api_type: str):
        self.api_type = api_type

    def _reserve(self) -> None:
        if not RateLimiter.reserve_call(self.api_type):
            raise RateLimitExceeded(f"API quota exhausted for {self.api_type}")

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        del serialized, messages, kwargs
        self._reserve()

    def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        del serialized, prompts, kwargs
        self._reserve()


def show_status():
    """Print current rate limiter status (CLI helper)."""
    print("\n" + "=" * 60)
    print("API Rate Limiter Status")
    print("=" * 60)

    status = RateLimiter.get_status()

    for api_type, info in status.items():
        print(f"\n{info['color']} {api_type}:")
        print(f"  RPM: {info['rpm_current']}/{info['rpm_limit']} ({info['rpm_pct']:.0%} used)")
        if info['tpm_limit'] > 0:
            print(f"  TPM: {info['tpm_current']}/{info['tpm_limit']} ({info['tpm_pct']:.0%} used)")
        print(f"  Status: {info['status']}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    # Demo usage
    print("Rate Limiter Demo")

    # Simulate API calls
    for i in range(10):
        result = RateLimiter.log_call("openai_chat", tokens=1000)
        print(f"Call {i+1}: RPM={result['rpm']}, Warning={result['warning']}")

    # Show status
    show_status()

    # Get remaining quota
    quota = RateLimiter.get_remaining_quota("openai_chat")
    print(f"\nRemaining: {quota['rpm_remaining']} RPM, {quota['tpm_remaining']} TPM")

"""Tests for Rate Limiter."""

import pytest
import time
import threading
from collections import defaultdict
from unittest.mock import patch, MagicMock

from tradingagents.monitoring.rate_limiter import RateLimiter, RateLimitConfig


class TestRateLimiterConfig:
    """Test RateLimitConfig."""

    def test_default_config(self):
        config = RateLimitConfig(rpm=100)
        assert config.rpm == 100
        assert config.tpm == 0
        assert config.warning_threshold == 0.9
        assert config.block_threshold == 0.95

    def test_custom_config(self):
        config = RateLimitConfig(
            rpm=200,
            tpm=50000,
            warning_threshold=0.8,
            block_threshold=0.9
        )
        assert config.rpm == 200
        assert config.tpm == 50000


class TestRateLimiterConfigure:
    """Test configure method."""

    def test_add_new_api(self):
        RateLimiter.configure("new_api", RateLimitConfig(rpm=50))
        assert "new_api" in RateLimiter.LIMITS
        assert RateLimiter.LIMITS["new_api"].rpm == 50

    def test_update_existing(self):
        original = RateLimiter.LIMITS.get("openai_chat", RateLimitConfig(rpm=500))
        RateLimiter.configure("openai_chat", RateLimitConfig(rpm=600))
        assert RateLimiter.LIMITS["openai_chat"].rpm == 600


class TestRateLimiterLogCall:
    """Test log_call method."""

    def setup_method(self):
        """Reset history before each test."""
        RateLimiter.reset()

    def test_basic_log(self):
        result = RateLimiter.log_call("openai_chat", tokens=500)

        assert result["api_type"] == "openai_chat"
        assert result["rpm"] == 1
        assert result["tpm"] == 500
        assert result["warning"] == False
        assert result["blocked"] == False

    def test_multiple_calls(self):
        for _ in range(5):
            RateLimiter.log_call("openai_chat")

        quota = RateLimiter.get_remaining_quota("openai_chat")
        assert quota["rpm_remaining"] == 495

    def test_warning_threshold(self):
        # Make 450 calls (90% of 500)
        for _ in range(450):
            RateLimiter.log_call("openai_chat")

        result = RateLimiter.log_call("openai_chat")  # 451st call
        assert result["warning"] == True

    def test_block_threshold(self):
        # Make 475 calls (95% of 500)
        for _ in range(475):
            RateLimiter.log_call("openai_chat")

        result = RateLimiter.log_call("openai_chat")  # 476th call
        assert result["blocked"] == True


class TestRateLimiterCheckCanCall:
    """Test check_can_call method."""

    def setup_method(self):
        RateLimiter.reset()

    def test_can_call_when_empty(self):
        assert RateLimiter.check_can_call("openai_chat") == True

    def test_can_call_under_limit(self):
        for _ in range(100):
            RateLimiter.log_call("openai_chat")

        assert RateLimiter.check_can_call("openai_chat") == True

    def test_cannot_call_over_threshold(self):
        for _ in range(480):  # Over 95% of 500
            RateLimiter.log_call("openai_chat")

        assert RateLimiter.check_can_call("openai_chat") == False

    def test_unknown_api_defaults_to_1000(self):
        assert RateLimiter.check_can_call("unknown_api") == True


class TestRateLimiterWaitIfNeeded:
    """Test wait_if_needed method."""

    def setup_method(self):
        RateLimiter.reset()

    def test_no_wait_when_under_limit(self):
        wait_time = RateLimiter.wait_if_needed("openai_chat")
        assert wait_time == 0

    @patch('time.sleep')
    def test_wait_when_over_threshold(self, mock_sleep):
        # Fill to 95% threshold
        for _ in range(475):
            RateLimiter.log_call("openai_chat")

        wait_time = RateLimiter.wait_if_needed("openai_chat")
        assert wait_time > 0
        mock_sleep.assert_called_once()

    @patch('time.sleep')
    def test_wait_when_token_limit_exceeded(self, mock_sleep):
        RateLimiter.log_call("openai_chat", tokens=190000)

        wait_time = RateLimiter.wait_if_needed("openai_chat")

        assert wait_time > 0
        mock_sleep.assert_called_once()


class TestRateLimiterGetRemainingQuota:
    """Test get_remaining_quota method."""

    def setup_method(self):
        RateLimiter.reset()

    def test_empty_history(self):
        quota = RateLimiter.get_remaining_quota("openai_chat")
        assert quota["rpm_remaining"] == 500
        assert quota["tpm_remaining"] == 200000

    def test_after_calls(self):
        for _ in range(100):
            RateLimiter.log_call("openai_chat", tokens=1000)

        quota = RateLimiter.get_remaining_quota("openai_chat")
        assert quota["rpm_remaining"] == 400
        assert quota["tpm_remaining"] == 100000

    def test_api_with_no_tpm_limit(self):
        quota = RateLimiter.get_remaining_quota("finnhub")
        assert quota["tpm_remaining"] == -1  # No TPM limit


class TestRateLimiterGetStatus:
    """Test get_status method."""

    def setup_method(self):
        RateLimiter.reset()

    def test_all_ok_status(self):
        status = RateLimiter.get_status()
        assert status["openai_chat"]["status"] == "ok"
        assert status["openai_chat"]["color"] == "🟢"

    def test_warning_status(self):
        for _ in range(450):
            RateLimiter.log_call("openai_chat")

        status = RateLimiter.get_status()
        assert status["openai_chat"]["status"] == "warning"
        assert status["openai_chat"]["color"] == "🟡"

    def test_blocked_status(self):
        for _ in range(480):
            RateLimiter.log_call("openai_chat")

        status = RateLimiter.get_status()
        assert status["openai_chat"]["status"] == "blocked"
        assert status["openai_chat"]["color"] == "🔴"


class TestRateLimiterReset:
    """Test reset method."""

    def test_reset_single_api(self):
        for _ in range(100):
            RateLimiter.log_call("openai_chat")

        RateLimiter.reset("openai_chat")
        quota = RateLimiter.get_remaining_quota("openai_chat")
        assert quota["rpm_remaining"] == 500

    def test_reset_all(self):
        for _ in range(50):
            RateLimiter.log_call("openai_chat")
            RateLimiter.log_call("finnhub")

        RateLimiter.reset()
        assert len(RateLimiter._call_history) == 0


class TestRateLimiterThreadSafety:
    """Test thread safety."""

    def setup_method(self):
        RateLimiter.reset()

    def test_concurrent_calls(self):
        """Test that concurrent calls don't cause race conditions."""
        errors = []

        def make_calls():
            try:
                for _ in range(100):
                    RateLimiter.log_call("openai_chat")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=make_calls) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        quota = RateLimiter.get_remaining_quota("openai_chat")
        assert quota["rpm_remaining"] == 500 - 500  # 5 threads * 100 calls


class TestRateLimiterHistoryTrim:
    """Test that old entries are trimmed."""

    def setup_method(self):
        RateLimiter.reset()

    @patch('time.time')
    def test_trim_old_entries(self, mock_time):
        # Start at time 0
        mock_time.return_value = 0
        for _ in range(100):
            RateLimiter.log_call("openai_chat")

        # Move to time 61 (after 60 second window)
        mock_time.return_value = 61
        RateLimiter.log_call("openai_chat")

        # History should only have 1 entry (the new one)
        assert len(RateLimiter._call_history["openai_chat"]) == 1

"""Config requirements follow the run mode.

The full SMTP trio was demanded unconditionally, so a rotated Gmail app
password broke --fast -- a mode that never sends email -- and took the
instant-alert channel down with the digest. Push-only runs instead require a
push channel, loudly: a --fast cron with no NTFY_TOPIC is a no-op every 15
minutes forever, which the old code reported as a warning nobody reads.
"""

from __future__ import annotations

import pytest

from alerters.hardware.native.config import Config, ConfigError


@pytest.fixture
def clean_env(monkeypatch):
    for name in (
        "SMTP_USER",
        "SMTP_PASSWORD",
        "MAIL_TO",
        "NTFY_TOPIC",
        "DISCORD_WEBHOOK",
    ):
        monkeypatch.delenv(name, raising=False)
    # Desktop notification is a push channel and defaults on for macOS, which
    # would otherwise satisfy every push requirement these tests assert about.
    monkeypatch.setenv("DESKTOP_NOTIFY", "0")
    # Keep the real .env out of these tests.
    monkeypatch.setattr("alerters.hardware.native.config.load_dotenv", lambda *a, **k: None)
    return monkeypatch


class TestEmailModes:
    def test_email_mode_requires_smtp(self, clean_env) -> None:
        with pytest.raises(ConfigError, match="SMTP_PASSWORD"):
            Config.load(need_email=True)

    def test_push_only_mode_works_without_smtp(self, clean_env) -> None:
        clean_env.setenv("NTFY_TOPIC", "some-topic")
        cfg = Config.load(need_email=False, need_push=True)
        assert cfg.ntfy_topic == "some-topic"
        assert cfg.smtp_password == ""


class TestPushModes:
    def test_push_only_mode_with_no_channel_is_an_error(self, clean_env) -> None:
        with pytest.raises(ConfigError, match="NTFY_TOPIC or DISCORD_WEBHOOK"):
            Config.load(need_email=False, need_push=True)

    def test_discord_alone_satisfies_the_push_requirement(self, clean_env) -> None:
        clean_env.setenv("DISCORD_WEBHOOK", "https://discord.example/hook")
        cfg = Config.load(need_email=False, need_push=True)
        assert cfg.discord_webhook

    def test_full_run_does_not_demand_a_push_channel(self, clean_env) -> None:
        """Push stays optional-with-warning on runs that also email."""
        for name, value in (
            ("SMTP_USER", "a@b.c"),
            ("SMTP_PASSWORD", "x"),
            ("MAIL_TO", "a@b.c"),
        ):
            clean_env.setenv(name, value)
        cfg = Config.load(need_email=True, need_push=False)
        assert cfg.ntfy_topic == ""

    def test_desktop_alone_satisfies_the_push_requirement(self, clean_env) -> None:
        """On the Mac that runs the cron there is always a desktop to notify,
        so a push-only run needs no remote channel at all."""
        clean_env.setenv("DESKTOP_NOTIFY", "1")
        cfg = Config.load(need_email=False, need_push=True)
        assert cfg.desktop_notify

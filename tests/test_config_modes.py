"""Credential requirements follow the run mode.

The full SMTP trio was demanded unconditionally, so a rotated Gmail app
password broke --fast -- a mode that never sends email -- and took the
instant-alert channel down with the digest. Push-only runs instead require a
push channel, loudly: a --fast cron with no NTFY_TOPIC is a no-op every 15
minutes forever, which the old code reported as a warning nobody reads.

Consolidation moved this from `ada.config.Config.load(need_email=, need_push=)`
into `dealcore.notify.channels(email=, push=)`, which is domain-agnostic, so
Steam and hardware both get the guarantee. The behaviour is unchanged; only
where it lives has moved.
"""

from __future__ import annotations

import pytest

from dealcore.notify import channels


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
    return monkeypatch


def _names(selected) -> set[str]:
    return {channel.name for channel in selected}


class TestEmailModes:
    def test_email_mode_requires_smtp(self, clean_env) -> None:
        with pytest.raises(ValueError, match="SMTP_PASSWORD"):
            channels(email=True, push=False, dry_run=False)

    def test_push_only_mode_works_without_smtp(self, clean_env) -> None:
        clean_env.setenv("NTFY_TOPIC", "some-topic")
        selected = channels(email=False, push=True, dry_run=False)
        assert "ntfy" in _names(selected)
        assert "email" not in _names(selected)


class TestPushModes:
    def test_push_only_mode_with_no_channel_is_an_error(self, clean_env) -> None:
        with pytest.raises(ValueError, match="NTFY_TOPIC, DISCORD_WEBHOOK"):
            channels(email=False, push=True, dry_run=False)

    def test_discord_alone_satisfies_the_push_requirement(self, clean_env) -> None:
        clean_env.setenv("DISCORD_WEBHOOK", "https://discord.example/hook")
        assert "discord" in _names(channels(email=False, push=True, dry_run=False))

    def test_full_run_does_not_demand_a_push_channel(self, clean_env) -> None:
        """Push stays optional on runs that also email."""
        for name, value in (
            ("SMTP_USER", "a@b.c"),
            ("SMTP_PASSWORD", "x"),
            ("MAIL_TO", "a@b.c"),
        ):
            clean_env.setenv(name, value)
        assert _names(channels(email=True, push=False, dry_run=False)) == {"email"}

    def test_desktop_alone_satisfies_the_push_requirement(self, clean_env) -> None:
        """On the Mac that runs the cron there is always a desktop to notify,
        so a push-only run needs no remote channel at all."""
        clean_env.setenv("DESKTOP_NOTIFY", "1")
        assert "desktop" in _names(channels(email=False, push=True, dry_run=False))


class TestDryRun:
    def test_a_dry_run_needs_no_credentials_at_all(self, clean_env) -> None:
        """New in the core: a dry run selects no channel, so a first invocation
        cannot fail on missing secrets before it has shown what it would send."""
        assert channels(email=True, push=True, dry_run=True) == ()


class TestDeliveryOrder:
    def test_urgent_channels_go_before_email(self, clean_env) -> None:
        """SMTP may stall for a minute before failing; push should not wait."""
        clean_env.setenv("NTFY_TOPIC", "some-topic")
        for name, value in (
            ("SMTP_USER", "a@b.c"),
            ("SMTP_PASSWORD", "x"),
            ("MAIL_TO", "a@b.c"),
        ):
            clean_env.setenv(name, value)
        selected = channels(email=True, push=True, dry_run=False)
        assert [channel.name for channel in selected][-1] == "email"

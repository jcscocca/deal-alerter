"""Official-shape API transcripts and a complete offline command-line run."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from alerters.__main__ import main
from alerters.steam.history import Candidate, SteamHistory
from alerters.steam.plugin import SteamPlugin
from alerters.steam.sources import ItadClient, Money, SteamSource, fetch_wishlist_appids, resolve_steam_id
from dealcore.config import overlay
from dealcore.notify import channels, send_desktop, send_discord, send_ntfy
from dealcore.report import render_html
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import Card, Report, SourceError

ROOT = Path(__file__).resolve().parents[1]


def transcript():
    return json.loads((ROOT / "examples/steam.json").read_text())


class SteamIOTests(unittest.TestCase):
    def test_complete_offline_cli_no_credentials_no_persistent_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            with redirect_stdout(StringIO()), patch("requests.Session.request") as network:
                result = main(["steam", "--demo", "--all", "--state-dir", str(root / "state"),
                               "--preview", str(root / "report.html")])
            self.assertEqual(result, 0)
            self.assertFalse((root / "state").exists())
            html = (root / "report.html").read_text()
            self.assertIn("ALL-TIME LOW", html)
            self.assertIn("synthetic prices", html)
            network.assert_not_called()

    def test_transport_has_shop_filter_batches_and_header_key(self):
        session = Mock()
        client = ItadClient("secret", "US", session=session)
        def request(method, url, **kwargs):
            response = Mock(status_code=200)
            response.json.return_value = {value: "id-" + value for value in kwargs["json"]}
            return response
        session.request.side_effect = request
        mapping = client.map_steam_appids(list(range(201)))
        self.assertEqual(len(mapping), 201)
        self.assertEqual([len(call.kwargs["json"]) for call in session.request.call_args_list], [200, 1])
        self.assertEqual(session.headers.update.call_args.args[0]["ITAD-API-Key"], "secret")
        self.assertNotIn("key", session.request.call_args.kwargs["params"])

    def test_nonsteam_deals_are_not_steam_prices(self):
        data = transcript()
        rows = data["responses"]["/games/prices/v3"]
        alien = copy.deepcopy(rows[0]["deals"][0])
        alien["shop"]["id"], alien["price"]["amount"] = 35, 1
        rows[0]["deals"].append(alien)
        client = ItadClient("", "US", replay=data)
        self.addCleanup(client.close)
        prices = client.steam_prices(["sample-game"])
        self.assertEqual(prices["sample-game"].deal.price.amount, 9.99)

    def test_history_sorted_and_currency_rejected(self):
        data = transcript()
        client = ItadClient("", "US", replay=data)
        self.addCleanup(client.close)
        points = client.steam_history("sample-game", years=5, currency="USD")
        self.assertEqual(points, sorted(points, key=lambda point: point.at))
        with self.assertRaises(SourceError):
            client.steam_history("sample-game", years=5, currency="EUR")

    def test_history_requests_explicit_window_and_store(self):
        client = ItadClient("", "US")
        self.addCleanup(client.close)
        client.json = Mock(return_value=[])
        client.steam_history("game", years=10, currency="USD")
        params = client.json.call_args.kwargs["params"]
        self.assertEqual(params["shops"], "61")
        self.assertIn("since", params)

    def test_empty_or_private_wishlist_never_silently_looks_complete(self):
        session, response = Mock(), Mock()
        session.get.return_value = response
        response.json.return_value = {"response": {}}
        with self.assertRaises(SourceError):
            fetch_wishlist_appids("76561198000000000", session)
        response.json.return_value = {"response": {"items": []}}
        self.assertEqual(fetch_wishlist_appids("76561198000000000", session), [])
        self.assertEqual(resolve_steam_id("https://steamcommunity.com/profiles/76561198000000000", session),
                         "76561198000000000")
        with self.assertRaises(SourceError):
            resolve_steam_id("https://evil.test/id/someone", session)

    def test_partial_id_mapping_cannot_authorize_forgetting(self):
        data = transcript()
        data["appids"].append(999)
        client = ItadClient("", "US", replay=data)
        self.addCleanup(client.close)
        source = SteamSource(client, "", 10)
        self.assertFalse(source.fetch().complete_sources)

    def test_retry_after_and_secret_safe_failure(self):
        session = Mock()
        first = Mock(status_code=429, headers={"Retry-After": "1"})
        second = Mock(status_code=200)
        second.json.return_value = []
        session.request.side_effect = [first, second]
        client = ItadClient("secret", "US", session=session)
        with patch("alerters.steam.sources.time.sleep") as sleep:
            self.assertEqual(client.json("GET", "/games/history/v2"), [])
        sleep.assert_called_once_with(1.0)
        session.request.side_effect = requests.ConnectionError("https://secret.example/token")
        with self.assertRaises(SourceError) as caught:
            client.json("GET", "/games/history/v2")
        self.assertNotIn("secret.example", str(caught.exception))

    def test_cache_persists_only_on_real_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = SteamPlugin(ROOT / "config/steam.toml", root, fixture=ROOT / "examples/steam.json")
            state = AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key)
            run(plugin, state, plugin.options, ())
            cache = plugin.state_dir / "games.json"
            self.assertTrue(cache.exists())
            before = cache.read_bytes()
            plugin = SteamPlugin(ROOT / "config/steam.toml", root, fixture=ROOT / "examples/steam.json")
            run(plugin, state, replace(plugin.options, dry_run=True, preview=root / "preview.html"), ())
            self.assertEqual(cache.read_bytes(), before)

    def test_threshold_overlay_reads_dataclass_defaults_and_rejects_typos(self):
        from alerters.steam.config import Thresholds
        self.assertEqual(overlay(Thresholds(), {}), Thresholds())
        self.assertEqual(overlay(Thresholds(), {"decent_cut": 60}).decent_cut, 60)
        with self.assertRaises(ValueError):
            overlay(Thresholds(), {"decent_cutt": 60})

    def test_notifications_keep_source_text_and_escape_attacker_input(self):
        card = Card('GPU " & (do shell script "bad")', "file:///tmp/bad", "$600", "STRONG",
                    "Look", "Provisional reference evidence", facts=("RTX 3090 BOX ONLY",))
        report = Report("Subject", "Heading", "Summary", "Footer", (card,))
        self.assertNotIn('href="file:', render_html(report))
        with patch("dealcore.notify.shutil.which", return_value=None), \
             patch("dealcore.notify.subprocess.run") as execute:
            send_desktop(report)
        command = execute.call_args.args[0]
        self.assertIn("RTX 3090 BOX ONLY", command[-2])
        self.assertIn(card.title, command[-1])
        with patch.dict(os.environ, {"NTFY_TOPIC": "private", "DISCORD_WEBHOOK": "https://example.test/hook"}), \
             patch("dealcore.notify.post") as post:
            send_ntfy(report)
            self.assertNotIn("click", post.call_args.kwargs["json"])
            send_discord(report)
            self.assertEqual(post.call_args.kwargs["json"]["allowed_mentions"], {"parse": []})

    def test_channel_requirements_follow_mode(self):
        with patch.dict(os.environ, {"DESKTOP_NOTIFY": "0"}, clear=True):
            self.assertEqual(channels(email=True, push=True, dry_run=True), ())
            with self.assertRaises(ValueError):
                channels(email=False, push=True, dry_run=False)
            with patch.dict(os.environ, {"NTFY_TOPIC": "private"}):
                self.assertEqual(channels(email=False, push=True, dry_run=False)[0].name, "ntfy")
                with patch.dict(os.environ, {"SMTP_USER": "user", "SMTP_PASSWORD": "password", "MAIL_TO": "recipient"}):
                    self.assertEqual([c.name for c in channels(email=True, push=True, dry_run=False)], ["ntfy", "email"])

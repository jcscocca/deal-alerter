"""Test collection rules for the consolidated repository.

`pending_entrypoint/` holds four tests inherited from ai-deal-alerter that
still import the retired `check_deals` module. They are kept verbatim rather
than deleted: they are coverage that must survive the hardware port.

What each needs before it can be collected again:

  test_stats.py            `show_stats` is now a HardwarePlugin method rather
                           than a free function over a History, so this needs a
                           constructed plugin rather than an import fix.
  test_dry_run.py          `evaluate` has no successor; the old entry point's
  test_threshold_bands.py  orchestration is split across dealcore.run and the
  test_trust.py            plugin's prepare/judge. `price_stats` likewise.
                           These need rewriting against the new pipeline.

Everything else from that repository now runs here against dealcore and the
vendored native modules.
"""
collect_ignore_glob = ["pending_entrypoint/*"]

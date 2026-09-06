"""Test collection rules for the consolidated repository.

`pending_entrypoint/` holds tests inherited from ai-deal-alerter that still
import the retired `check_deals` module. They are kept verbatim rather than
deleted: they are the coverage that must survive the hardware port, and they
become collectable again once the hardware domain runs through
`dealcore.run` instead of the old standalone entry point.
"""
collect_ignore_glob = ["pending_entrypoint/*"]

"""Fetch, judge, deduplicate, report, notify, persist. No shopping rules."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import IntEnum
from math import isfinite
from pathlib import Path

from .notify import Channel
from .report import render_html
from .state import AlertState, atomic_write
from .types import AccumulatedHistory, Assessment, Domain, Listing, SourceError
from .verdict import Improvement, qualifies


@dataclass(frozen=True)
class RunOptions:
    email_floor: IntEnum
    push_floor: IntEnum | None
    improvement: Improvement
    remind_after_days: int = 30
    dry_run: bool = False
    force: bool = False
    include_others: bool = False
    quiet_when_empty: bool = False
    preview: Path = Path("report.html")


@dataclass
class RunResult:
    assessments: list[Assessment]
    problems: list[str]

    @property
    def exit_code(self) -> int:
        return 1 if self.problems else 0


def dedupe(listings: list[Listing], key) -> list[Listing]:
    best: dict[str, Listing] = {}
    for listing in listings:
        identity = key(listing)
        previous = best.get(identity)
        if previous is None:
            best[identity] = listing
            continue
        rank = lambda row: row.price if row.price is not None else float("inf")
        winner = listing if rank(listing) < rank(previous) else previous
        # A different search must not launder an unloggable option into history.
        best[identity] = replace(winner, loggable=previous.loggable and listing.loggable,
                                multi_variant=previous.multi_variant or listing.multi_variant)
    return list(best.values())


def run(domain: Domain, state: AlertState, options: RunOptions,
        channels: tuple[Channel, ...], *, now: datetime | None = None) -> RunResult:
    now = now or datetime.now(timezone.utc)
    problems: list[str] = []
    assessments: list[Assessment] = []
    live, complete = set(), set()
    fetched, succeeded = [], 0
    try:
        for source in domain.sources:
            try:
                batch = source.fetch()
                # Materialize and validate before accepting any completeness claim.
                rows = list(batch.listings)
                keys = {domain.key(row) for row in rows}
                fetched.extend(rows)
                live.update(keys)
                complete.update(batch.complete_sources)
                succeeded += 1
            except SourceError as exc:
                problems.append(f"{source.name}: {exc}")
            except Exception as exc:
                problems.append(f"{source.name}: {type(exc).__name__}")
        if not succeeded:
            return RunResult([], problems or ["No sources configured"])

        pending = []
        for listing in dedupe(fetched, domain.key):
            try:
                candidate = domain.prepare(listing)
                if candidate is None:
                    continue
                evidence = domain.history.read(candidate)
                item = domain.judge(candidate, evidence)
                if item is None:
                    continue
                if type(item.verdict) is not domain.bands:
                    raise TypeError("Plugin returned another domain's verdict")
                if tuple(name for name, _ in item.axes) != domain.axes:
                    raise ValueError("Assessment axes disagree with the plugin declaration")
                if not isfinite(item.price) or item.price < 0:
                    raise ValueError("Assessment price is not finite and nonnegative")
                if item.key != domain.key(listing):
                    raise ValueError("Assessment changed the listing's alert identity")
                assessments.append(item)
                # The source veto is irreversible; judgment may only tighten it.
                if item.loggable and listing.loggable and not listing.multi_variant:
                    pending.append((candidate, item))
            except SourceError as exc:
                problems.append(f"{domain.key(listing)}: {exc}")
            except Exception as exc:
                # Its raw key remains live: failed history is not an ended sale.
                problems.append(f"{domain.key(listing)}: {type(exc).__name__}")

        assessments.sort(key=lambda item: (int(item.verdict), *item.rank), reverse=True)
        # No candidate in this run participates in another candidate's benchmark.
        if not options.dry_run and isinstance(domain.history, AccumulatedHistory):
            domain.history.append(pending)

        worthy = [item for item in assessments if qualifies(item, options.email_floor)]
        others = [item for item in assessments if not qualifies(item, options.email_floor)]
        others = others if options.include_others else []
        for channel in channels:
            floor = options.email_floor if channel.kind == "email" else options.push_floor
            if floor is None:
                continue
            selected = [item for item in assessments if qualifies(item, floor)
                        and (options.force or state.is_new(item, channel.name, options.improvement,
                                                         options.remind_after_days, now))]
            groups = [selected] if channel.kind == "email" else [[item] for item in selected]
            for group in groups:
                if not group and (options.quiet_when_empty or problems):
                    continue
                try:
                    report = domain.report(group, others if channel.kind == "email" else [], problems)
                    if not options.dry_run:
                        channel.send(report)
                        state.record(group, channel.name, now)
                        # Persist successful deliveries before trying another channel.
                        state.save(now)
                except Exception as exc:
                    problems.append(f"{channel.name}: delivery failed ({type(exc).__name__})")

        preview_buys = [item for item in worthy if options.force or state.is_new(
            item, "email", options.improvement, options.remind_after_days, now)]
        if options.dry_run:
            atomic_write(options.preview, render_html(domain.report(preview_buys, others, problems)))
        return RunResult(assessments, problems)
    finally:
        try:
            if not options.dry_run and succeeded:
                state.forget_missing(live, complete)
                # History persistence can fail without erasing delivery receipts.
                try:
                    domain.persist()
                finally:
                    state.save(now)
        finally:
            domain.close()

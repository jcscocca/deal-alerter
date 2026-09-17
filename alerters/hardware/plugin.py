"""Adapter around the real hardware modules, copied by import_hardware.py.

No approximation of match.py lives here. Its original code is a prerequisite.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from dealcore.run import RunOptions
from dealcore.state import atomic_write
from dealcore.types import AccumulatedHistory, Assessment, Card, FetchResult, Listing, Report
from dealcore.verdict import Improvement, band, money
from . import manual
from .identity import group_id, normalise_key
from .manual import ManualSource


@dataclass(frozen=True)
class Candidate:
    listing: Listing
    match: object
    hunt: object
    condition: str


class SourceAdapter:
    def __init__(self, source) -> None:
        self.source, self.name = source, source.name

    def fetch(self) -> FetchResult:
        # Finite searches do not prove delisting, even when the request succeeds.
        return FetchResult(self.source.fetch())


class HardwarePlugin:
    name, axes, default_mode = "hardware", ("cheapness", "value", "capability"), "full"
    normalise_key = staticmethod(normalise_key)

    def __init__(self, config_path: Path, state_root: Path, *, daily: bool = True) -> None:
        try:
            from .native import catalog, config, history, match, rig, verdict
            from .native.sources import build_sources
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.startswith("alerters.hardware.native"):
                raise ValueError("Run: python scripts/import_hardware.py ../ai-deal-alerter") from None
            raise
        self.catalog, self.rig, self.verdict, self.matcher = catalog, rig, verdict, match.match
        self.bands = verdict.Verdict
        try:
            self.cfg = config.Config.load(config_path, config_path.with_name("watchlist.toml"))
        except config.ConfigError as exc:
            raise ValueError(str(exc)) from None
        if self.cfg.country != "US":
            raise ValueError("Hardware catalog references are USD; this adapter requires country=US")
        self.state_dir = state_root / self.name / self.cfg.country
        self.log_path, self.daily = self.state_dir / "prices.jsonl", daily
        self.manual_path = self.state_dir / "manual.jsonl"
        # Last, so a listing you entered by hand loses a dedup tie to the same
        # listing found by a real source, which knows its condition and seller.
        self.sources = tuple(SourceAdapter(source) for source in build_sources(self.cfg)) + (
            SourceAdapter(ManualSource(self.manual_path)),)
        self.options = RunOptions(band(self.bands, self.cfg.digest_at), band(self.bands, self.cfg.push_at),
                                  Improvement(verdict.DOLLAR, 4.0), self.cfg.remind_after_days,
                                  include_others=True)
        self.watched = self.cfg.all_watched_parts()
        self.seen = self.matched = 0
        # Rebuild from the committed authority, never from a possibly newer,
        # uncommitted SQLite cache. Even import/maintenance is private to this run.
        self.temporary = TemporaryDirectory(prefix="hardware-history-")
        try:
            self.log = history.History(Path(self.temporary.name) / "prices.db")
            if self.log_path.exists():
                self.log.import_jsonl(self.log_path)
        except Exception:
            if hasattr(self, "log"):
                self.log.close()
            self.temporary.cleanup()
            raise
        self.history = AccumulatedHistory(self.read_history, self.append)

    @staticmethod
    def key(listing: Listing) -> str:
        return f"{listing.source}:{group_id(listing.listing_id)}"

    def prepare(self, listing: Listing) -> Candidate | None:
        self.seen += 1
        # A manual entry is a standing instruction rather than a search hit:
        # you typed it in deliberately and it stays until you delete the line.
        # Ageing it out would quietly stop watching a listing you asked to watch.
        if listing.source != "manual" and listing.age_hours > self.cfg.max_listing_age_hours:
            return None
        result = self.matcher(listing.title, body=listing.body, price=listing.price,
                              multi_variant=listing.multi_variant)
        if result.junk or result.part is None or result.unit_price is None:
            return None
        hunt = self.watched.get(result.part.key)
        if hunt is None:
            return None
        self.matched += 1
        return Candidate(listing, result, hunt, listing.condition_hint or result.condition)

    def read_history(self, candidate: Candidate):
        # Used and new are never mixed. A refurb A6000 and a sealed one are
        # different products that happen to share a name, and pooling them
        # makes the percentile meaningless in both directions.
        args = dict(min_observations=self.cfg.thresholds.min_observations,
                    min_span_days=self.cfg.thresholds.min_observation_days)
        sold = self.log.stats(candidate.match.part.key, candidate.condition, sold_only=True, **args)
        # Confirmed sales are preferred only when they have earned confidence.
        # Otherwise retain the original pooled-asking/sold fallback, explicitly.
        return sold if sold.trustworthy else self.log.stats(candidate.match.part.key, candidate.condition, **args)

    def judge(self, candidate: Candidate, stats) -> Assessment | None:
        listing, result, hunt = candidate.listing, candidate.match, candidate.hunt
        item = self.verdict.assess(listing_id=listing.listing_id, source=listing.source,
            part=result.part, title=listing.title, url=listing.url, unit_price=result.unit_price,
            quantity=result.quantity, condition=candidate.condition, posted_at=listing.posted_at,
            stats=stats, thresholds=self.cfg.thresholds, mining_risk=result.mining_risk,
            seller_risk=listing.seller_risk, seller_note=listing.seller_note, loggable=listing.loggable,
            is_system=result.is_system, is_bundle=result.is_bundle, multi_variant=listing.multi_variant,
            target_price=hunt.target, hunt_name=hunt.name, psu_headroom_w=self.cfg.psu_headroom_w)
        if item is None:
            return None
        upgrade = item.vram_after > item.vram_before + 1
        if not upgrade:
            # The original target promotion ran AFTER this cap and could undo it.
            # Keep the claimed invariant independent of configurable alert floors.
            item = replace(item, verdict=min(item.verdict, self.bands.GOOD))
        return Assessment(self.key(listing), item.unit_price, item.verdict, item,
            rank=(float(item.loggable), -item.dollars_per_gb), alertable=upgrade,
            loggable=item.loggable, axes=(("cheapness", item.reason),
                ("value", f"{money(item.dollars_per_gb, whole_above=100)}/GB, "
                          f"{money(item.dollars_per_gb_bandwidth, whole_above=100)}/GB-TB/s"),
                ("capability", item.unlock)))

    def append(self, pairs: list[tuple[Candidate, Assessment]]) -> None:
        for candidate, assessment in pairs:
            listing, result = candidate.listing, candidate.match
            # One answer to observation eligibility: judgment's loggable flag,
            # additionally constrained by the source veto in the core.
            if not assessment.loggable:
                continue
            self.log.record(part_key=result.part.key, condition=candidate.condition,
                unit_price=result.unit_price, source=listing.source, listing_id=listing.listing_id,
                title=listing.title, quantity=result.quantity, sold=listing.sold, seen_at=listing.posted_at)
        self.log.commit()

    def arbitrage(self, assessments: list[Assessment]) -> dict[str, str]:
        """Prebuilts asking less than the cheapest loose card they contain.

        This is the one case where a whole machine tells you something. A system
        price is refused as evidence about the card inside it -- that is what
        `is_system` does everywhere else in this plugin -- but the comparison
        runs the other way here: the loose cards are the evidence and the
        machine is the candidate. Nothing is recorded, so the refusal stands.

        Only loose cards this run was willing to log count as the benchmark. An
        untrusted price is not a price, and using one would either invent an
        opportunity out of a bait listing or bury a real one behind it.

        An asking-price gap is not profit. Neither side has sold, the machine
        may not hold the card its title claims, and parting one out means
        finding a buyer for the remaining computer.
        """
        loose: dict[str, list[Assessment]] = {}
        for item in assessments:
            detail = item.detail
            if detail.is_system or detail.is_bundle or detail.multi_variant:
                continue
            if not item.loggable:
                continue
            loose.setdefault(detail.part.key, []).append(item)

        signals: dict[str, str] = {}
        for item in assessments:
            detail = item.detail
            if not detail.is_system:
                continue
            pool = loose.get(detail.part.key, [])
            # Condition drives used-card prices harder than anything else, so a
            # same-condition comparison is the only one worth calling confirmed.
            matched = [row for row in pool
                       if row.detail.condition == detail.condition
                       and detail.condition not in ("unknown", "parts")]
            pool = matched or pool
            if not pool:
                continue
            cheapest = min(pool, key=lambda row: row.detail.unit_price)
            saving = cheapest.detail.unit_price - detail.unit_price
            if saving <= self.verdict.DOLLAR:
                continue
            headline = (f"Whole machine at {money(detail.unit_price, decimals=0)} "
                        f"undercuts the cheapest loose {detail.part.name} this run at "
                        f"{money(cheapest.detail.unit_price, decimals=0)} -- "
                        f"{money(saving, decimals=0)} of room before the rest of the PC costs anything.")
            signals[item.key] = headline + (
                " Potential only: conditions differ or are unstated, so the two prices are not like for like."
                if not matched else
                " Same condition on both sides. Confirm the machine actually contains the card before anything else.")
        return signals

    def card(self, assessment: Assessment, signal: str | None = None) -> Card:
        item = assessment.detail
        facts = [item.title, f"via {item.source}; {item.condition}",
                 f"{money(item.dollars_per_gb, decimals=0)}/GB; "
                 f"{money(item.dollars_per_gb_bandwidth, decimals=0)}/GB-TB/s; "
                 f"{item.part.vram_gb}GB; {item.part.bandwidth_gb_s:,} GB/s", item.unlock]
        if item.quantity > 1:
            facts.append(f"Quantity {item.quantity}; lot total {money(item.total_price, decimals=0)}")
        warnings = []
        if item.confidence == "reference":
            # Below min_observations (or the minimum time span), native judgment
            # falls back to catalog references and says so instead of pretending
            # to a confidence it does not have. Keep the warning in every channel.
            warnings.append("Judged against a catalog reference, not observed history; provisional.")
        if item.fit and not item.fit.ok:
            warnings.append(item.fit.summary)
        if item.mining_risk != "low":
            warnings.append(f"Mining risk: {item.mining_risk}")
        if item.multi_variant:
            warnings.append("Confirm which option this price buys; not recorded in price history.")
        if signal:
            warnings.append(signal)
        models = sorted(self.rig.LADDER, key=lambda model: model.params_b)
        before, after = self.rig.largest_model_at(item.vram_before), self.rig.largest_model_at(item.vram_after)
        rung = lambda model: models.index(model) + 1 if model else 0
        left = round(rung(before) / len(models) * 100)
        gain = max(0, round(rung(after) / len(models) * 100) - left)
        colours = {
            self.bands.GRAIL: ("#5b2d8e", "#ece0f8"),
            self.bands.EXCEPTIONAL: ("#0b6b3a", "#d7f2e3"),
            self.bands.STRONG: ("#0b6b3a", "#d7f2e3"),
            self.bands.GOOD: ("#1c5d99", "#dbebfa"),
            self.bands.FAIR: ("#8a5a00", "#fdf0d5"),
            self.bands.PASS: ("#5c5f66", "#eceef1"),
        }
        fg, bg = colours[item.verdict]
        return Card(item.part.name, item.url, money(item.unit_price, decimals=0),
                    item.verdict.label + (" · HITS YOUR TARGET" if item.target_hit else ""),
                    item.headline, item.reason, tuple(facts), tuple(warnings),
                    bar=((left, "#9aa0a6"), (gain, "#2f6f4e"), (100-left-gain, "#e3e6ea")),
                    bar_labels=(f"now {item.vram_before:.0f}GB ({before.name if before else 'below ladder'})",
                                f"after {item.vram_after:.0f}GB ({after.name if after else 'below ladder'})"),
                    foreground=fg, background=bg,
                    priority=5 if item.verdict >= self.bands.EXCEPTIONAL else
                             4 if item.verdict >= self.bands.STRONG else
                             2 if item.verdict == self.bands.PASS else 3)

    def report(self, buys: list[Assessment], others: list[Assessment], problems: list[str]) -> Report:
        signals = self.arbitrage(buys + others)
        cards = tuple(self.card(item, signals.get(item.key)) for item in buys)
        subject = (f"{cards[0].badge}: {cards[0].title} at {cards[0].price}" if len(cards) == 1 else
                   f"{len(cards)} new AI hardware recommendations")
        # A prebuilt is normally a PASS and lands in `others`, which is cut to
        # fifteen. Undercutting its own GPU is the only reason to read that far,
        # so those rows go first; sorted() is stable, so the rest keep their order.
        rest = sorted(others, key=lambda item: item.key not in signals)
        found = sum(1 for item in buys + others if item.key in signals)
        summary = f"{self.matched} of {self.seen} unique listings matched your watchlist."
        if found:
            summary += (f" {found} prebuilt{'s' if found != 1 else ''} priced under the cheapest "
                        "loose card of the same GPU.")
        return Report(subject, "AI workstation deals", summary,
                      f"{self.log.total_observations():,} prices logged; condition buckets remain separate.",
                      cards, tuple(self.card(item, signals.get(item.key)) for item in rest[:15]),
                      tuple(problems))

    def persist(self) -> None:
        if self.daily:
            # The existing runner prunes at 730 days; 'forever' was its docstring,
            # not its behavior. Retain the actual retention policy explicitly.
            self.log.prune(keep_days=730)
            self.log.commit()
        path = Path(self.temporary.name) / "prices.jsonl"
        self.log.export_jsonl(path)
        atomic_write(self.log_path, path.read_text(encoding="utf-8"))

    def add_manual(self, **fields) -> None:
        """Record a listing you found yourself, and say what it will be judged as.

        The match runs here rather than at the next poll because a title that
        names nothing in the catalog, or a part no hunt is watching, would
        otherwise be filed and silently never appear again.
        """
        entry = manual.add(self.manual_path, **fields)
        print(f"Recorded {entry.url}")
        result = self.matcher(entry.title, price=entry.price)
        if result.junk or result.part is None:
            print("  No catalog part in that title, so nothing will be judged. "
                  "Give the title the listing's own wording, or add the part to catalog.py.")
            return
        watched = self.watched.get(result.part.key)
        print(f"  Matched {result.part.name}"
              + (f" x{result.quantity}" if result.quantity > 1 else "")
              + (f", hunted by \"{watched.name}\"." if watched else
                 ". No hunt covers this part, so it will not be judged -- add it to watchlist.toml."))

    def show_stats(self) -> None:
        """What the log knows. Useful for deciding whether to trust the verdicts yet.

        The table is the retired entry point's, restored: the port had
        flattened it to raw floats and dropped the low and p25 columns, which
        are what reference prices get recalibrated against.
        """
        total = self.log.total_observations()
        print(f"{total:,} observations logged at {self.log_path}\n")
        if not total:
            print("Nothing yet. Verdicts will use catalog reference prices until the")
            print("log fills up -- let the scheduled runs collect for a week or two.")
            return
        header = f"{'part':<38} {'cond':<7} {'n':>4} {'low':>9} {'p25':>9} {'median':>9}"
        print(header)
        print("-" * len(header))
        cell = lambda value: money(value, decimals=0) if value is not None else "-"
        for part in self.catalog.PARTS:
            # Conditions, not bucket names: stats() re-maps whatever it's given
            # through bucket_for(), and "refurb" isn't a condition -- it would
            # fall through the default and report the used bucket a second time.
            for condition in ("used", "refurbished", "new"):
                stats = self.log.stats(part.key, condition,
                    min_observations=self.cfg.thresholds.min_observations,
                    min_span_days=self.cfg.thresholds.min_observation_days)
                if not stats.count:
                    continue
                mark = "" if stats.trustworthy else "  (too few to rank)"
                print(f"{part.name:<38} {stats.bucket:<7} {stats.count:>4} {cell(stats.low):>9} "
                      f"{cell(stats.p25):>9} {cell(stats.median):>9}{mark}")

    def close(self) -> None:
        try:
            self.log.close()
        finally:
            self.temporary.cleanup()

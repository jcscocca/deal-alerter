"""Group actionable monitor failures without turning listing uncertainty into outages."""
from __future__ import annotations

from collections import Counter, defaultdict

from .community import SLICKDEALS_COVERAGE

HEALTH_GRACE_SECONDS = 10 * 60
LISTING_UNVERIFIED = "Offer found but seller/configuration/landed total cannot be confirmed"
LABELS = {"hp": "HP", "newegg": "Newegg", "skytech": "Skytech", "cyberpowerpc": "CyberPowerPC",
          "ibuypower": "iBUYPOWER", "reddit": "Reddit", "slickdeals": "Slickdeals",
          "ebay": "eBay", "apple-refurb": "Apple refurbished"}


def source_of(key, job):
    kind = job.get("kind") or key.split("-", 1)[0]
    return job.get("source", "legacy") if kind == "legacy" else kind.removeprefix("discover-")


def problem_key(problem, status):
    if problem == "Monitor heartbeat is stale":
        return "monitor:heartbeat"
    key = problem.partition(":")[0]
    if key in status.get("jobs", {}):
        return "source:" + source_of(key, status["jobs"][key])
    return "coverage:" + problem


def migrate_key(key, status):
    if key.startswith("job:"):
        job_id = key[4:]
        if job_id in status.get("jobs", {}):
            return "source:" + source_of(job_id, status["jobs"][job_id])
    return key


def failure_type(error):
    # Recognize the old verification error while schedules migrate naturally on
    # their next check. These offers must remain unconfirmed in shopping data.
    if error == LISTING_UNVERIFIED:
        return "listing"
    if error in ("Path disallowed by robots.txt", "Waiting for published crawl delay"):
        return "limitation"
    if error.startswith(("Network request failed", "Host is backing off", "HTTP 429", "HTTP 503",
                         "Access denied (HTTP", "Cannot verify robots policy", "Bot challenge;",
                         "Legacy source unavailable/rate limited", "Reddit API rate limit")):
        return "connection"
    return "check"


def coverage_limitation(problem):
    return (problem == SLICKDEALS_COVERAGE or ": discovery cap reached;" in problem
            or problem == "HP browser: custom/configuration-selector URLs remain unverified")


def incidents(status, problems, prior, now):
    """Return current incidents, including their persisted first-observed time.

    All raw diagnostics remain in watchdog.json. Only sustained incidents are
    eligible for a push. A successful request resolves earlier connection errors
    on the same retailer, even if individual jobs are still waiting to retry.
    """
    jobs = status.get("jobs", {})
    successes = defaultdict(float)
    for key, job in jobs.items():
        source = source_of(key, job)
        successes[source] = max(successes[source], job.get("last_fetch_success", 0), job.get("last_success", 0))
    groups, summaries = defaultdict(list), {}
    for problem in problems:
        key = problem_key(problem, status)
        job_id = problem.partition(":")[0]
        if job_id in jobs:
            job = jobs[job_id]
            category = failure_type(job.get("error", ""))
            # Recovery/verification notes cannot hide a scheduler that has stopped
            # revisiting this job long after its own saved retry deadline.
            if "next" in job and now - job["next"] > max(600, job.get("interval", 0) * 3):
                category = "check"
            if category in ("listing", "limitation"):
                continue
            if category == "connection" and successes[source_of(job_id, job)] > job.get("last_error_at", 0):
                continue
            groups[key].append(category)
        elif not coverage_limitation(problem):
            summaries[key] = problem
    for key, categories in groups.items():
        counts = Counter(categories)
        details = []
        if counts["connection"]:
            details.append(f"{counts['connection']} connection/backoff check" + ("s" if counts["connection"] != 1 else ""))
        if counts["check"]:
            details.append(f"{counts['check']} failed or overdue check" + ("s" if counts["check"] != 1 else ""))
        source = key.removeprefix("source:")
        summaries[key] = f"{LABELS.get(source, source)}: " + "; ".join(details)
    previous = prior.get("incidents", {})
    current = {}
    for key, summary in summaries.items():
        since = previous.get(key, {}).get("since", now)
        if type(since) not in (int, float) or not 0 <= since <= now:
            since = now
        current[key] = {"since": since, "summary": summary}
    return current


def eligible_incidents(current, now):
    return {key: item for key, item in current.items()
            if key == "monitor:heartbeat" or now - item["since"] >= HEALTH_GRACE_SECONDS}

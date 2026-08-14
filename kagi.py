"""Kagi API client: search and extract.

Two functions, one shared key, a timeout each, and no retry logic. Errors
raise — a bad key or a rate limit should stop the run and say so, not be
swallowed into an empty report. Containing errors so one bad source can't end
the run is Backlog item 3.

Endpoints and payload shapes were verified against the live API in Tasks 0
and 2; see the Task 0 notes in AGENTS.md for what they return.
"""

import datetime as dt

import httpx

import config

# Seconds to wait on the HTTP call itself. Both sit above the server-side
# budgets below, so a slow page trips Kagi's limit and returns a per-page
# error rather than killing our connection.
SEARCH_TIMEOUT = 30
EXTRACT_TIMEOUT = 60

# Seconds Kagi spends fetching, as a budget for the whole batch. 10 is the
# documented maximum; article pages are slow and we would rather wait than
# lose the text.
EXTRACT_BUDGET = 10

# One client for the whole run, so the connection is reused across the eight
# or so searches a run makes.
_client = httpx.Client(
    base_url=config.KAGI_API,
    headers={"Authorization": f"Bearer {config.KAGI_KEY}"},
)


def _post(path, body, timeout):
    """POST and return the envelope's `data`, raising on any error Kagi reports."""
    response = _client.post(path, json=body, timeout=timeout)
    response.raise_for_status()
    envelope = response.json()

    # Kagi reports problems in an `error` list inside the envelope. Surface the
    # message; the bare status code is rarely enough to act on.
    errors = envelope.get("error") or []
    if errors:
        messages = "; ".join(error.get("message", str(error)) for error in errors)
        raise RuntimeError(f"Kagi {path}: {messages}")

    return envelope.get("data")


def search(query, lens_id=None):
    """Run one search. Returns a list of results.

    Each result is {url, title, snippet, time, ...} where `time` is an ISO
    publication timestamp — the reason most items get a date for free.

    `lens_id` narrows the search and is set per term rather than per run; see
    config.SEARCH_TERMS.
    """
    body = {"query": query, "limit": config.SEARCH_RESULTS_PER_TERM}
    if lens_id:
        body["lens_id"] = lens_id

    # Restrict to recently published or updated pages. `filters.after` is the
    # only time limit the API actually applies — the lens equivalents
    # (`time_relative`, `time_after`) are accepted and silently ignored.
    if config.SEARCH_WINDOW_DAYS is not None:
        after = dt.date.today() - dt.timedelta(days=config.SEARCH_WINDOW_DAYS)
        body["filters"] = {"after": after.isoformat()}

    data = _post("/search", body, SEARCH_TIMEOUT) or {}

    # `data` is keyed by result type. We only ever want web pages; images,
    # videos and the rest of the keys are ignored.
    return data.get("search") or []


def extract(urls):
    """Fetch the text of several pages in one call. Returns a list of results.

    Each result is {url, markdown, error}. `error` is set per page, so one
    dead link does not cost us the other nine — check it before reading
    `markdown`.
    """
    if not urls:
        return []
    if len(urls) > config.KAGI_EXTRACT_LIMIT:
        raise ValueError(
            f"extract takes at most {config.KAGI_EXTRACT_LIMIT} URLs, got {len(urls)}"
        )

    body = {
        "pages": [{"url": url} for url in urls],
        "timeout": EXTRACT_BUDGET,
    }
    return _post("/extract", body, EXTRACT_TIMEOUT) or []

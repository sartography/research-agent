"""Cross-run memory: which URLs we've already put in a report.

One JSON file, config.SEEN_FILE, mapping url_key(url) -> {url, title,
first_seen}. Without this a run has no memory and re-reports the same Gartner
press release, or the same event, every day. AGENTS.md backlog item 1.

`load()` once near the top of main(), `is_new()` and `mark_seen()` as items
are decided, `save()` once the decisions are made. The dict lives on this
module rather than being threaded through every step, since holding state is
the one thing this file is for.
"""

import datetime as dt
import json
from urllib.parse import parse_qsl, urlencode, urlsplit

import config

# Query parameters that identify a campaign rather than an article. Anything
# starting with utm_ goes too.
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}

_seen = {}


def url_key(url):
    """A URL reduced to what makes it the same article or event.

    Only ever used as a dictionary key — callers keep the URL they arrived
    with, so nothing here can damage a link that gets published. That is what
    makes it safe to be aggressive: scheme dropped so http and https collapse,
    www. and a trailing slash dropped, tracking parameters removed, and the
    rest sorted so parameter order stops mattering.
    """
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    query = sorted(
        (name, value)
        for name, value in parse_qsl(parts.query)
        if name.lower() not in TRACKING_PARAMS and not name.lower().startswith("utm_")
    )
    return f"{host}{path}?{urlencode(query)}" if query else f"{host}{path}"


def load():
    """Read the seen store from disk into memory. Empty on first run."""
    global _seen
    _seen = json.loads(config.SEEN_FILE.read_text()) if config.SEEN_FILE.exists() else {}


def is_new(url):
    return url_key(url) not in _seen


def mark_seen(item):
    """Record one item's URL as seen. Existing entries are left alone, so
    first_seen keeps meaning the day we first noticed it, not the day we
    last saw it again.
    """
    key = url_key(item["url"])
    if key not in _seen:
        _seen[key] = {
            "url": item["url"],
            "title": item["title"],
            "first_seen": dt.date.today().isoformat(),
        }


def save():
    config.SEEN_FILE.write_text(json.dumps(_seen, indent=2, sort_keys=True))

"""Orchestrator. Runs one research pass and writes a report.

    uv run main.py

The pipeline, in order:

    collect  ->  dedupe  ->  triage  ->  extract  ->  synthesize  ->  copy edit  ->  report
     (wide)                 (cheap)     (narrow)     (strong)        (mid)

The report is written to `reports/YYYY-MM-DD.md` and printed. Running twice in
one day overwrites that day's file rather than adding a second one.

Collection, triage, and rendering all live in this file for now. They get their
own modules when this stops being readable in one sitting.

Everything is collected two ways, by Kagi search or by feed. Both carry
publication dates, which is what lets the run tell new from old; a source
that offers neither does not come in at all.
"""

import calendar
import datetime as dt
import html
import json
import re
import sys
from urllib.parse import urlsplit

import feedparser

import config
import kagi
import llm
import state
from state import url_key


# --- Steps -------------------------------------------------------------------
# Each returns plain data; nothing is stashed on globals.


def make_item(url, title, source_type, source, snippet="", published_at=None):
    """Build one item record. All three collectors return a list of these.

    `source` is the entry from config — a search term, feed, or page. Its
    threshold and group ride along so later steps never have to look the
    source back up.

    A search term is named by the term itself unless it carries a `name`,
    which is how a site: query reads as its site in the report.
    """
    return {
        "url": url,
        "title": title or "",
        "source_type": source_type,
        "source_name": source.get("name") or source.get("term"),
        "snippet": snippet or "",
        "published_at": published_at or "date unknown",
        "threshold": source["threshold"],
        "group": source.get("group"),
    }


def collect_from_search(terms):
    """Task 4. One Kagi search per term. Returns item records.

    Each entry is {term, threshold}, the same shape as a feed or a page.
    Kagi caps the results at config.SEARCH_RESULTS_PER_TERM and drops anything
    older than config.SEARCH_WINDOW_DAYS, so there is nothing to trim here.
    """
    items = []
    for source in terms:
        results = kagi.search(source["term"], lens_id=source.get("lens"))
        lens = f"  lens={source['lens']}" if source.get("lens") else ""
        print(f"  search {source['term']:<32.32} {len(results):>3}{lens}")
        for result in results:
            items.append(
                make_item(
                    url=result["url"],
                    title=result.get("title"),
                    source_type="search",
                    source=source,
                    snippet=result.get("snippet"),
                    published_at=result.get("time"),
                )
            )
    return items


def entry_date(entry):
    """The publication time of a feed entry, as UTC, or None if it has none.

    feedparser hands back a `struct_time` already converted to UTC, so the
    only work here is turning it into a datetime we can compare. `published`
    is the real date; `updated` is the fallback for feeds that only carry one
    (Atom feeds often do).
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return dt.datetime.fromtimestamp(calendar.timegm(parsed), dt.timezone.utc)


def clean_snippet(text):
    """Feed summaries are HTML, and substack summaries can be a whole post.

    Triage reads every snippet in one call, so strip the tags and cut it to
    config.SNIPPET_CHARS before it gets there.
    """
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(html.unescape(text).split())[: config.SNIPPET_CHARS]


def collect_from_feeds(feeds):
    """Task 5. feedparser over every feed. Publication dates come free here.

    Keeps entries published in the last config.FEED_WINDOW_DAYS days. Undated
    entries are dropped: with no seen-URL store yet (Backlog item 1), the date
    window is the only thing stopping a feed from re-reporting its whole front
    page every run.
    """
    items = []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=config.FEED_WINDOW_DAYS)

    for source in feeds:
        feed = feedparser.parse(source["url"])

        # feedparser reports a broken fetch or unparsable XML in `bozo` rather
        # than raising. Minor XML quirks set it too, so only complain when it
        # also cost us the entries — an empty feed we can't explain is the
        # quietly empty report the MVP is trying to avoid.
        if not feed.entries:
            raise RuntimeError(
                f"{source['name']} ({source['url']}) returned no entries: "
                f"{feed.get('bozo_exception') or 'empty feed'}"
            )

        kept = []
        for entry in feed.entries:
            published = entry_date(entry)
            if published is None or published < cutoff:
                continue
            kept.append(
                make_item(
                    url=entry.get("link"),
                    title=entry.get("title"),
                    source_type="feed",
                    source=source,
                    snippet=clean_snippet(entry.get("summary")),
                    published_at=published.isoformat(),
                )
            )

        print(f"  feed   {source['name']:<32.32} {len(kept):>3} of {len(feed.entries):>3}")
        items += kept

    return items


def collect_from_event_feeds(feeds):
    """Event feeds. Same parser as Task 5, but the window looks forward: an
    entry's date is when the event happens, not when it was published, so an
    event stays in for config.EVENT_WINDOW_DAYS ahead rather than behind.

    Past events (the feed can carry a few) and events too far out both drop,
    for the same reason Task 5 drops undated posts: nothing here should ever
    grow to re-report the same listing every run.
    """
    items = []
    now = dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(days=config.EVENT_WINDOW_DAYS)

    for source in feeds:
        feed = feedparser.parse(source["url"])

        if not feed.entries:
            raise RuntimeError(
                f"{source['name']} ({source['url']}) returned no entries: "
                f"{feed.get('bozo_exception') or 'empty feed'}"
            )

        kept = []
        for entry in feed.entries:
            when = entry_date(entry)
            if when is None or when < now or when > horizon:
                continue
            kept.append(
                make_item(
                    url=entry.get("link"),
                    title=entry.get("title"),
                    source_type="event",
                    source=source,
                    snippet=clean_snippet(entry.get("summary")),
                    published_at=when.isoformat(),
                )
            )

        print(f"  event  {source['name']:<32.32} {len(kept):>3} of {len(feed.entries):>3}")
        items += kept

    return items


def parse_json_list(reply, task):
    """Read a JSON list out of a model reply.

    Models like to wrap JSON in a code fence or introduce it with a sentence,
    so take everything between the outermost brackets rather than trusting the
    reply to be bare JSON.
    """
    start, end = reply.find("["), reply.rfind("]")
    if start == -1 or end == -1:
        raise RuntimeError(f"{task}: expected a JSON list, got: {reply[:200]}")
    return json.loads(reply[start : end + 1])


def metadata_score(item):
    """How much a record carries, for picking which copy to keep.

    Ordered by scarcity rather than by size. A date is the rarest thing a
    record can have and the one nothing downstream can reconstruct, so it
    outranks a longer snippet.
    """
    return (
        item["published_at"] != "date unknown",
        bool(item["title"]),
        len(item["snippet"]),
    )


def merge_into(keep, other):
    """Fold a duplicate into the record we are keeping.

    Gaps are filled rather than overwritten, so a feed's date can rescue a
    search result that arrived without one. The two judgment fields are
    deliberately generous: an item claimed by any competitor source stays a
    competitor item, and one found by both a hand-picked feed and a broad
    search term is judged by the looser of the two — some source vouched for
    it, and triage can only drop things.
    """
    if keep["published_at"] == "date unknown":
        keep["published_at"] = other["published_at"]
    if not keep["title"]:
        keep["title"] = other["title"]
    if len(other["snippet"]) > len(keep["snippet"]):
        keep["snippet"] = other["snippet"]

    keep["group"] = keep["group"] or other["group"]
    if config.TRIAGE_THRESHOLDS[other["threshold"]] < config.TRIAGE_THRESHOLDS[keep["threshold"]]:
        keep["threshold"] = other["threshold"]

    for name in other["sources"]:
        if name not in keep["sources"]:
            keep["sources"].append(name)


def dedupe(items):
    """Task 7. Collapse duplicate URLs, keeping the richest record. Within a
    single run only — cross-run filtering needs the seen store (Backlog 1).

    Every record gains a `sources` list naming each place the URL turned up.
    Collapsing the copies would otherwise destroy exactly the signal Task 10
    calls trending: the same story reaching us through several independent
    sources on the same day.
    """
    by_key = {}
    for item in items:
        item["sources"] = [item["source_name"]]
        key = url_key(item["url"])
        kept = by_key.get(key)

        if kept is None:
            by_key[key] = item
            continue

        # Keep the richer copy, then fill its gaps from the poorer one.
        if metadata_score(item) > metadata_score(kept):
            merge_into(item, kept)
            by_key[key] = item
        else:
            merge_into(kept, item)

    deduped = list(by_key.values())
    repeats = sum(1 for item in deduped if len(item["sources"]) > 1)
    print(f"  {len(items)} collected, {len(deduped)} unique, {repeats} found by more than one source")
    return deduped


def drop_seen(items, label):
    """Filter out items state.is_new() says we've already reported, and mark
    the rest seen right away.

    Marking happens here, before triage, not after — a low-scoring item that
    triage would drop anyway still gets marked, so it does not get
    re-collected and re-scored on every future run forever. Backlog item 1.
    """
    new = [item for item in items if state.is_new(item["url"])]
    for item in new:
        state.mark_seen(item)

    skipped = len(items) - len(new)
    if skipped:
        print(f"  {skipped} of {len(items)} {label} already reported, skipping")
    return new


def triage(items, cap=None):
    """Task 8. One cheap-model call over all titles and snippets, scoring each
    0-5. Keeps items at or above config.TRIAGE_THRESHOLD, then the top `cap`
    by score (config.MAX_ARTICLES if not given).

    The cap is the main thing keeping a run cheap: it decides how many pages
    Task 9 extracts and how much text reaches the synthesize call. Events use
    their own cap (config.MAX_EVENTS) since they are never extracted.
    """
    cap = config.MAX_ARTICLES if cap is None else cap
    if not items:
        return []

    listing = "\n".join(
        f"{number}. {item['title']}\n   {item['snippet']}"
        for number, item in enumerate(items, 1)
    )
    reply = llm.ask(
        config.TRIAGE_MODEL,
        config.TRIAGE_PROMPT.format(count=len(items), items=listing),
    )

    scores = {}
    for row in parse_json_list(reply, "triage"):
        try:
            scores[int(row["id"])] = int(row["score"])
        except (KeyError, TypeError, ValueError):
            continue  # one malformed row must not cost us the other forty

    # An item the model skipped scores 0 rather than sneaking through unjudged.
    for number, item in enumerate(items, 1):
        item["relevance"] = scores.get(number, 0)

    kept = [item for item in items if item["relevance"] >= config.TRIAGE_THRESHOLD]

    # Best score first, then most recent. "date unknown" sorts last rather
    # than first, which is where a string comparison would otherwise put it.
    kept.sort(
        key=lambda item: (
            item["relevance"],
            item["published_at"] if item["published_at"] != "date unknown" else "",
        ),
        reverse=True,
    )

    counts = {score: sum(1 for i in items if i["relevance"] == score) for score in range(5, -1, -1)}
    print(
        f"  scored {len(items)} items: "
        + ", ".join(f"{count} at {score}" for score, count in counts.items())
    )
    if len(scores) != len(items):
        print(f"  {len(items) - len(scores)} items went unscored and were treated as 0")
    print(f"  {len(kept)} at or above threshold {config.TRIAGE_THRESHOLD}, keeping top {cap}")

    return kept[:cap]


def truncate(text):
    """Cut article text down to config.ARTICLE_CHAR_BUDGET.

    Extract returns tens of thousands of characters — Task 0 measured one page
    at 98K — and all of it would otherwise reach the synthesize call. The cut
    lands on a line break where there is one nearby, and says so, since a
    paragraph ending mid-sentence with no explanation reads like a fact.
    """
    if len(text) <= config.ARTICLE_CHAR_BUDGET:
        return text

    kept = text[: config.ARTICLE_CHAR_BUDGET]
    break_at = kept.rfind("\n")
    if break_at > config.ARTICLE_CHAR_BUDGET // 2:
        kept = kept[:break_at]
    return kept + "\n\n[truncated]"


def extract_batch(urls):
    """Extract several pages, and survive a URL that poisons the whole batch.

    Kagi usually reports a page it cannot read in that page's own `error`
    field. But some URLs — a feed's `.xml` is the one we hit — make it answer
    the *entire* batch with no data at all: HTTP 200, no error in the
    envelope, nothing. One such URL among ten cost us all ten and produced an
    empty report that looked like a quiet day.

    So when a batch comes back short, ask again one URL at a time. That costs
    a handful of extra calls on the rare day it happens, and it names the
    offender in the log instead of losing the run.
    """
    results = kagi.extract(urls)
    if len(results) == len(urls):
        return results

    print(f"  batch of {len(urls)} returned {len(results)}; retrying one at a time")
    results = []
    for url in urls:
        one = kagi.extract([url])
        results += one or [{"url": url, "error": "extract returned nothing for this url alone"}]
    return results


def extract_articles(items):
    """Task 9. One batched Kagi extract call for all survivors. Truncates each
    page to config.ARTICLE_CHAR_BUDGET.

    Items whose page cannot be read are dropped rather than carried forward
    empty: a title with no text behind it is exactly what fills a report with
    confident sentences about pages nobody read.
    """
    if not items:
        return []

    # One call per batch of config.KAGI_EXTRACT_LIMIT. Today MAX_ARTICLES is
    # the same number, so this is a single request; raising the cap (Backlog
    # item 5) should not silently start failing.
    results = []
    urls = [item["url"] for item in items]
    for start in range(0, len(urls), config.KAGI_EXTRACT_LIMIT):
        results += extract_batch(urls[start : start + config.KAGI_EXTRACT_LIMIT])

    # Match on the normalized URL rather than on position: Kagi echoes the URL
    # back, sometimes redirected, and a silently misaligned zip would attach
    # one article's text to another article's title.
    by_key = {url_key(result.get("url") or ""): result for result in results}

    if len(results) != len(urls):
        print(f"  extract returned {len(results)} results for {len(urls)} urls")

    kept = []
    for position, item in enumerate(items):
        result = by_key.get(url_key(item["url"]))
        if result is None and len(results) == len(items):
            result = results[position]

        if result is None:
            print(f"  skip {item['url'][:64]}  - no result came back for this url")
            continue

        error = result.get("error")
        markdown = result.get("markdown") or ""
        if error or not markdown.strip():
            print(f"  skip {item['url'][:64]}  - {error or 'page came back empty'}")
            continue

        item["text"] = truncate(markdown)
        print(f"  read {item['url'][:64]}  {len(markdown):>6} chars -> {len(item['text'])}")
        kept.append(item)

    print(f"  {len(kept)} of {len(items)} pages readable")
    return kept


def article_block(number, item):
    """One article as the synthesize call sees it: a header of everything we
    know about where it came from, then the text.

    The source list is spelled out rather than counted. The model is asked to
    name the sources when it calls something trending, and two names it can
    read are what let it do that honestly.
    """
    found_by = ", ".join(item["sources"])
    if len(item["sources"]) > 1:
        found_by += f"  ({len(item['sources'])} independent sources)"
    return (
        f"[{number}] {item['title']}\n"
        f"    url: {item['url']}\n"
        f"    published: {item['published_at']}\n"
        f"    found by: {found_by}\n"
        f"    relevance: {item['relevance']} of 5\n"
        f"\n{item['text']}\n"
    )


def synthesize(items):
    """Task 10. One strong-model call over the truncated articles. Groups by
    topic, flags anything appearing in more than one source as trending, and
    carries a source URL on every claim. Returns draft Markdown.

    Every article goes into one call rather than one call each, because the
    whole job here is seeing the day as a whole: what groups with what, and
    what turned up twice. A per-article step that keeps breadth up without
    sending this much raw text is Backlog item 6.

    Length and tone are set here rather than in the copy edit. A five-minute
    read and a report that states facts instead of admiring them are decisions
    about what to write, and an editor forbidden to change facts cannot make
    them after the fact.
    """
    if not items:
        return "## Nothing to report\n\nNo articles survived today's screening."

    articles = "\n".join(article_block(number, item) for number, item in enumerate(items, 1))

    # Opus thinks by default and max_tokens bounds thinking and reply together,
    # so this is deliberately roomy: a tight budget cuts the report off partway
    # rather than making it shorter.
    draft = llm.ask(
        config.SYNTHESIZE_MODEL,
        config.SYNTHESIZE_PROMPT.format(articles=articles),
        max_tokens=16000,
    )

    print(f"  {len(items)} articles ({len(articles):,} chars) -> {len(draft):,} char draft")
    return draft


LINK_PATTERN = re.compile(r"\]\(\s*(https?://[^\s)]+)")


def find_urls(markdown):
    """Every URL linked from a Markdown document, as a set."""
    return set(LINK_PATTERN.findall(markdown))


def copy_edit(draft):
    """Task 11. Second call applying Strunk and White. Style only — it must
    not introduce claims or drop citations. Returns edited Markdown.

    The one thing this step can do that we would not survive is quietly lose a
    link. A dropped citation leaves a claim the reader cannot check, and it
    reads perfectly — nothing about the edited paragraph looks wrong. So the
    links are counted, and an edit that costs one is thrown away: the draft is
    already a publishable report, and prose is not worth a source.
    """
    edited = llm.ask(config.COPY_EDIT_MODEL, config.COPY_EDIT_PROMPT.format(draft=draft), max_tokens=16000)

    before, after = find_urls(draft), find_urls(edited)
    lost = before - after
    if lost:
        print(f"  copy edit dropped {len(lost)} of {len(before)} links; keeping the draft")
        for url in sorted(lost):
            print(f"    lost {url[:72]}")
        return draft

    print(f"  {len(draft):,} chars -> {len(edited):,}, all {len(before)} links intact")
    return edited


def publisher(url):
    """Who published something, for the References list.

    The host, not `source_name`. A feed's source_name is its publisher, but a
    search result's is the query that found it, and "Business process
    automation" listed as the source of a PR Newswire release is a search term
    wearing a publisher's clothes.
    """
    return urlsplit(url).netloc.lower().removeprefix("www.")


def references(edited, items):
    """The References section: every item the report actually links to, with
    its publication time and URL.

    Built from the items rather than from the body, because the body carries
    only what the writing needed — a link and whatever the sentence called it.
    The item record still holds the title as its source published it and the
    publication time, which is what Constraint 4 asks for.

    An item the report never cited is left out. `url_key()` does the matching,
    so a link the writing step reproduced with a tracking parameter still finds
    its item.

    **A body with no links at all lists everything instead**, and says so. That
    is not the same situation as an article being left out: it means the
    writing step stopped producing links, and filtering on them would silently
    delete the References section rather than report the problem. It has
    happened once already — a prompt edit dropped the inline-link rule, and the
    report shipped with a bare `## References` heading and no complaint.
    """
    cited = {url_key(url) for url in find_urls(edited)}
    if cited:
        listed = [item for item in items if url_key(item["url"]) in cited]
        if len(listed) < len(items):
            print(f"  {len(items) - len(listed)} of {len(items)} articles were read but never cited")
    else:
        listed = items
        print(f"  the report body links to nothing; listing all {len(items)} articles read")

    lines = ["## References", ""]
    for number, item in enumerate(listed, 1):
        lines.append(f"{number}. **{item['title']}** — {publisher(item['url'])}, {item['published_at']}")
        lines.append(f"   {item['url']}")

    return "\n".join(lines)


# dctech.events titles carry the event's own date as a trailing parenthetical
# — "AI Agents at Work (September 9, 2026)" — which would just repeat the date
# events_section() prints from published_at. Stripped for display only; the
# stored title is untouched, since a differently-shaped event feed added later
# may not carry this suffix at all.
EVENT_TITLE_DATE = re.compile(
    r"\s*\((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r" \d{1,2}, \d{4}\)\s*$"
)


def events_section(events):
    """The Upcoming Events section: a short, date-ordered list of events that
    cleared triage. Built directly from the feed data rather than through
    synthesize — a title, date and link is all there is to say about a
    calendar listing, so there is no prose worth an LLM call for.

    Kept as its own section rather than folded into the synthesized body,
    since it answers a different question than the news does: not "what
    happened", but "what's coming up".
    """
    lines = ["## Upcoming Events", ""]
    if not events:
        lines.append("Nothing upcoming cleared today's screening.")
        return "\n".join(lines)

    ordered = sorted(events, key=lambda item: item["published_at"])
    for item in ordered:
        when = dt.datetime.fromisoformat(item["published_at"]).strftime("%A, %B %d")
        title = EVENT_TITLE_DATE.sub("", item["title"])
        lines.append(f"- **[{title}]({item['url']})** — {when}")
    return "\n".join(lines)


def render(edited, items, events):
    """Task 12. Write reports/YYYY-MM-DD.md — a title, the edited body, the
    Upcoming Events section, and References. Returns the path written.

    The title belongs here rather than in the report itself. Synthesize is told
    not to write one, because the model does not know the date the run happened
    on and would date the report from whatever the articles said.

    One file per day, overwritten on a re-run rather than appended to. Running
    twice in an afternoon should leave one report, not two halves of one.
    """
    config.REPORTS_DIR.mkdir(exist_ok=True)

    today = dt.date.today()
    path = config.REPORTS_DIR / f"{today.isoformat()}.md"
    path.write_text(
        f"# Research report — {today.strftime('%d %B %Y')}\n\n"
        f"{edited.strip()}\n\n"
        f"{events_section(events)}\n\n"
        f"{references(edited, items)}\n"
    )
    return path


# --- Wiring ------------------------------------------------------------------


def check_keys():
    """Fail with one clear line rather than a KeyError deep in the run."""
    missing = [
        name
        for name, value in (
            ("KAGI_KEY", config.KAGI_KEY),
            ("ANTHROPIC_API_KEY", config.ANTHROPIC_API_KEY),
        )
        if not value
    ]
    if missing:
        print(f"Missing {' and '.join(missing)}. Set them in .env or the environment.")
        return False
    return True


def show(items):
    """Print what we collected, so a partial run is still worth watching.

    An item found by more than one source is marked with its count — that is
    the first hint of what Task 10 will call trending.
    """
    for item in items:
        sources = item.get("sources") or [item["source_name"]]
        mark = f" x{len(sources)}" if len(sources) > 1 else ""
        score = f"[{item['relevance']}] " if "relevance" in item else ""
        print(
            f"  {score}{item['published_at']:<22.22} {item['source_name']:<24.24} "
            f"{item['url'][:56]}{mark}"
        )

    dated = sum(1 for item in items if item["published_at"] != "date unknown")
    print(f"\n  {len(items)} items, {dated} dated, {len(items) - dated} undated")


def main():
    if not check_keys():
        return 1

    state.load()

    print("Collecting...")
    items = collect_from_search(config.SEARCH_TERMS)
    items += collect_from_feeds(config.FEEDS)
    events = collect_from_event_feeds(config.EVENT_FEEDS)

    print()
    items = dedupe(items)
    events = dedupe(events)

    items = drop_seen(items, "articles")
    events = drop_seen(events, "events")
    state.save()

    print("\nTriaging...")
    items = triage(items)
    events = triage(events, cap=config.MAX_EVENTS)

    print()
    show(items)

    print("\nExtracting...")
    items = extract_articles(items)

    print("\nSynthesizing...")
    draft = synthesize(items)

    print("\nCopy editing...")
    edited = copy_edit(draft)

    print("\nRendering...")
    path = render(edited, items, events)

    print("\n" + "=" * 78 + "\n")
    print(path.read_text())
    print("=" * 78)
    print(f"\nWritten to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

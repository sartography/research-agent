
# Purpose
A research agent that runs daily, researching topics related to our core business, and providing a curated report on a daily basis. Breakig importatnt news, events and speaking opportunities, popular blog posts should be surfaced.  It checks in with me after the research, and I can provide feedback on the findings.  I may recommend updating the research topics (the source lists in config.py), or adding some important information to should be added to the long term context of the agent (This AGENTS.md) file.  We may over time also decide to add new items to a file called SOURCES.md which should contain a curated list of sources we will search. 

# Search Engine
Kagi should be used for search.  The results of this search should be sent to 
Take advantage of Kagi's lens feature, and recommend lens settings on an ongoing basis.

# LLM
The LLM should be configurable and callable via API.  
Each LLM task can be assigned to a different agent.  No need to send all traffic to claude.

# Technology
Minimal libraries, tools, and configuration.  
Python code that is clean and easy for a novice programmer to read and understand. 

# Constraints
1. For any final reports back to the user, assure that the content is run through a copy edit pass with instructions to apply Struct and White Elements of Style 
2. Summerize usefulness of search terms, and suggest changes.
4. The final report must include links to original sources (References).
3. Group similar topic areas and note anything that appears to be trending.  
4. Include the time each Reference was published.

# Order of Tasks
1. Run Kagi Search on search terms in TOPICS
2. Run Kagi Extract on the extraction websites 
3. Extract results from RSS Feeds

---

# Implementation Plan

Two parts. The **MVP** proves the tools work and walks one run end to end. The
**Backlog** holds everything deliberately left out, to be added as we iterate.

## Shape of the pipeline

Collection is wide and cheap; reading is narrow and careful. Every candidate is
found first, filtered on its title and snippet, and only the survivors are
fetched in full.

Candidates arrive two ways, by Kagi search or by feed. Both carry publication
dates, and dates are what let a run tell new from old, so a source offering
neither does not come in at all — Task 6 is the story of learning that.

```
collect  →  dedupe  →  triage  →  extract  →  synthesize  →  copy edit  →  report
 (wide)                (cheap)    (narrow)    (strong)       (mid)
```

---

# Part 1 — MVP

## What the MVP proves

1. The Kagi search API answers, with a key we hold.
2. The Kagi extract API returns usable article text.
3. RSS parsing works on the substacks and feeds in `config.FEEDS`.
4. An LLM call works, and the triage → synthesize → copy edit chain produces a
   report we would actually read.

Nothing else. It is allowed to crash, print ugly errors, and re-report the same
article two days in a row.

## Simplifying rules for the MVP

These are the choices that keep it small. Each has a matching Backlog item.

- **No state.** No `seen.json`, no run metrics. Dedupe within a single run only.
- **No history.** Yesterday's report is just a file in `reports/`; nothing reads it.
- **One triage threshold** for every source, not per-source gates.
- **No digest step.** With a hard cap of ~10 articles, truncated article text
  goes straight into the synthesize call. Digests are a cost and volume
  optimization we do not need yet.
- **Publication dates only where they are free** — from the feed entry, or from
  the Kagi search result if present. Otherwise "date unknown".
- **Crash on failure.** No retries, no per-source error trapping. If Kagi is
  down we want to see the traceback, not a quietly empty report.
- **No cron, no dry run, no logging framework.** Run it by hand; `print()` is
  the log.

## Files

Four files. Merge any that feel too thin.

| File | Responsibility |
|---|--------------------------------------------------|
| `config.py` | Keys, model names, tuning constants, and the source lists. |
| `kagi.py` | Kagi API client: `search()` and `extract()`. |
| `llm.py` | One function: `ask(model, prompt) -> str`. |
| `main.py` | Everything else: collect, triage, synthesize, edit, write. |

Collection, triage and rendering all live in `main.py` for now. They get their
own modules when `main.py` stops being readable in one sitting.

## Dependencies

Three: `anthropic`, `httpx`, `feedparser`. Add to `pyproject.toml`.

## The item record

A plain dictionary, gaining fields as it moves:

| Field | Set by | Notes |
|---|---|---|
| `url` | collect | Dedupe key |
| `title` | collect | |
| `source_type` | collect | `search` or `feed` |
| `source_name` | collect | The search term, or the site it came from |
| `snippet` | collect | Search snippet or feed summary |
| `published_at` | collect | Free-form string, or "date unknown" |
| `sources` | dedupe | Every source that found this URL; more than one is the trending signal |
| `relevance` | triage | 0–5 |
| `text` | extract | Article text, truncated |

## LLM assignment

Swappable in `config.py`; starting points, not commitments.

| Task | Model |
|---|---|
| Triage | Claude Haiku 4.5 |
| Synthesize | Claude Opus 5 |
| Copy edit | Claude Sonnet 5 |

## MVP tasks

### Task 0: Smoke test — done, then deleted
A throwaway `smoke_test.py` made one Kagi search call, one Kagi extract call
on a known URL, and one LLM call. All three passed, and the file has since
been removed — its value was the answers below, not the code. What it settled:

- **Base URL** `https://kagi.com/api/v1`, auth `Authorization: Bearer <key>`.
- **Search** is `POST /search` with a JSON body: `query`, plus optional
  `limit`, `lens_id`, `workflow`, and a `filters` object. Results come back
  under `data.search` as `{url, title, snippet, time, ...}`, where `time` is an
  ISO publication timestamp — **but only about 61% of the time**. Measured in
  Task 2 across all eight search terms, 49 of 80 results carried one, and the
  spread is wide: "Business Analytics" and "Agentic Standards" returned 10 of
  10, "BPMN" returned 0 of 10. Reference-heavy queries that surface homepages
  and spec pages get nothing. So dates are *partly* free from search; the rest
  read "date unknown" until Backlog item 4 resolves them from the page.
- **Extract** is `POST /extract` and takes **up to 10 URLs in one call**
  (`pages: [{url}, ...]`), returning `data[].markdown` per page with a
  per-page `error` field. It returns Markdown, not plain text, and it is
  verbose — a Wikipedia article came back as 98K characters, which is why
  Task 9 truncates. The per-page `error` is not the only way it fails:
  certain URLs make the whole batch return `data: null` with a 200 and no
  error at all. See Task 9.
- The key covers both endpoints. Per-call cost and quota are still unchecked;
  see open question 1.

### Task 1: Scaffolding and config — done
`config.py` loads `.env` on import and holds the keys, the model names, the
Kagi endpoint, and the tuning constants (`TRIAGE_THRESHOLD`, `MAX_ARTICLES`,
`ARTICLE_CHAR_BUDGET`, `FEED_WINDOW_DAYS`, `SEARCH_RESULTS_PER_TERM`). The
numbers the MVP turns on live there rather than being scattered through the
steps.

It also carries a six-line `.env` loader, run on import, rather than taking a
dependency on `python-dotenv`.

`main.py` holds the pipeline: every step below is a stub that names its task,
so `uv run main.py` stops at the first unfinished one and says which. `llm.py`
is complete — one `ask(model, prompt, max_tokens)`.

### Task 2: Kagi client — done
`kagi.py`: `search(query)` and `extract(urls)` — extract is **batched**,
taking up to 10 URLs. One shared `httpx.Client`, a timeout each, no retries.
Errors raise, including the ones Kagi reports in the envelope's `error` list
rather than in the status code.

`extract` returns a **per-page** `error` field, and it fires in practice —
`bpmn.org` came back "No data returned" while the other two pages in the same
batch were fine. Callers must check `error` before reading `markdown`; one
dead link must not cost us the other nine.

### Task 3: Parse the source list — removed
The sources now live in `config.py` as `SEARCH_TERMS` and `FEEDS`, so there is
nothing to parse. TOPICS.md is no longer read. (There was a third list,
`PAGES`; Task 6 says why it is gone.)

The lists are grouped by collector rather than by category, so each one feeds
exactly one step: `SEARCH_TERMS` to Task 4, `FEEDS` to Task 5. Camunda sits in
`FEEDS` with the other feeds because that is the
collector it needs, and carries `group = "competitor"` so the report can still
put it in the competitor section. Substack `/feed` suffixes are written into
the URLs rather than applied by a rule.

All three lists share a shape: every entry is a dict carrying a `threshold` of
`loose`, `normal`, or `strict`, including individual search terms. That records
the judgment that used to sit in TOPICS.md prose ("should be filtered", "likely
of interest"). The MVP ignores it and gates everything on `TRIAGE_THRESHOLD`;
Backlog item 2 reads it instead, with no data changes needed.
`config.TRIAGE_THRESHOLDS` maps each name to a number on triage's 0-5 scale.

Search-term thresholds track how *precise* a term is rather than how much we
care about the subject: a narrow term like `BPMN` returns little enough that
most of it is worth reading, while `"AI Agents"` returns mostly marketing copy
that happens to match. Opening guesses only — Backlog item 10 measures how each
term performs and says which to move.

### Task 4: Search collector — done
`collect_from_search()` runs one Kagi search per entry in `config.SEARCH_TERMS`
and returns item records. No trimming: Kagi already caps results at
`SEARCH_RESULTS_PER_TERM` and drops anything older than `SEARCH_WINDOW_DAYS`.

**Lenses are per term, not per run.** Each entry may carry an optional `lens`,
passed as `lens_id` on that one search. The right lens depends on the term — a
narrowing lens that rescues a broad industry phrase would throw away most of
what a precise term is looking for.

`make_item()` builds the record, and Tasks 5 and 6 use it too so the field
names cannot drift between collectors. It takes the source entry whole, so
each item carries its own `threshold` and `group` and no later step has to look
the source back up from a URL. That is two fields beyond the item record table
above; both exist for Backlog items 2 and 7.

`main()` currently stops after this step and prints what it collected. The
calls for Tasks 5 onward are commented out in place, one line each.

### Task 5: Feed collector — done
`collect_from_feeds()`: `feedparser` over every entry in `config.FEEDS`,
keeping what was published inside `FEED_WINDOW_DAYS`. Dates do come free —
every kept entry carried one.

Two decisions the code makes:

- **Undated entries are dropped.** With no seen-URL store (Backlog item 1),
  the date window is the only thing stopping a feed from re-reporting its
  whole front page every run.
- **An empty feed raises.** feedparser reports a failed fetch in `bozo` rather
  than raising, so a dead feed would otherwise pass silently as zero entries.

Feed summaries are HTML, and substack's run to the length of the post, so
`clean_snippet()` strips the tags and cuts them to `config.SNIPPET_CHARS` —
triage reads every snippet in one call.

First real run: 23 items from six feeds, all dated. Hacker News alone gave 20
of them, which is the argument for Backlog item 2 — one threshold cannot both
admit a hand-picked substack and hold back the HN firehose. The Camunda feed
lists some posts twice; Task 7 collapses them.

### Task 6: Index-page collector — built, then removed
This step scraped listing pages: one batched Kagi extract over a `PAGES` list,
then one cheap LLM call per page asking for the article links in the returned
Markdown. It worked — Forrester 12 links, HFS 15, Appian 8, Pega 15 — and it
is gone anyway. What one run showed:

- **Gartner returned Kagi's "No data returned from crawlers."** Not a
  permission problem: their robots.txt allows `/en/newsroom`, which is absent
  from the `User-agent: *` disallow list and appears as an explicit `Allow:`
  even in the restrictive AI-crawler group. Only CCBot is refused outright,
  and Kagi is unnamed, so it falls under `*`. The block is a Cloudflare
  challenge that fingerprints the client — a plain `curl` gets a "Just a
  moment..." interstitial for the same robots.txt a browser renders, and 403
  on the newsroom. Kagi's crawler meets the same door, and had already failed
  this way in Task 2.
- **A listing page carries no dates and no recency.** Search has
  `SEARCH_WINDOW_DAYS` and feeds have `FEED_WINDOW_DAYS`; a page has neither.
  Forrester's offered press releases from 2024 and 2025 next to this week's,
  and every item arrived as "date unknown", so nothing downstream could tell
  them apart. Worse, HFS's 15 links were all **six weeks old** — the site had
  not published since June 30 — and the step reported them as a healthy
  harvest.

**Both replacements are cheaper than the thing they replace.**

*Gartner moved to search.* `site:gartner.com/en/newsroom` in `SEARCH_TERMS`.
Kagi's index holds the pages its crawler cannot fetch, so search returns the
press releases with titles, snippets and dates — everything but the article
body. Verified: one result under the 1-day window, correctly dated. A search
term may now carry an optional `name`, so this one reads as "Gartner" rather
than as its query.

*Forrester and HFS moved to feeds.* Both publish one; neither links it from
the page we were scraping. `forrester.com/blogs/feed/` is their analyst blogs
rather than the press newsroom — commentary instead of announcements, and the
better read. `hfsresearch.com/feed/` turns out to be exactly the `/news/` page
we were scraping, with the dates attached, which is how the six-week gap
became visible at all. Under `FEED_WINDOW_DAYS` HFS now contributes 0 items
on a quiet day instead of 15 stale ones.

*Appian and Pega were dropped.* Neither publishes a feed at any path worth
guessing, so nothing carries them. Camunda is now the only competitor source;
Backlog item 7 says what that costs.

**Why `site:` is not a general answer.** Tested against all four pages, it
returns a relevance-ranked slice of the archive rather than recent posts: a
2019 Pega explainer outranks last week's, and 20-30% of results carry no
`time`, which `filters.after` then drops. All four windowed `site:` queries
returned **0** results while extraction returned 12/15/8/15. Newsrooms are
the exception — dated, heavily linked, indexed fast — which is why Gartner
works and the blogs do not.

**What this leaves.** Two collectors, search and feed, both of which carry
publication dates. Dates are what let the run tell new from old, so a source
that offers neither now stays out. `config.PAGES`, `LINK_FINDER_MODEL`,
`INDEX_LINKS_PER_PAGE` and `INDEX_CHAR_BUDGET` are all gone.
`parse_json_list()` stays — Task 8 needs it.

This narrows `# Order of Tasks` step 2: Kagi extract is no longer a collector,
only the way Task 9 fetches article bodies for items search and feeds found.

### Task 7: Merge and dedupe — done
`dedupe()` collapses duplicate URLs, keeping the record with the most
metadata. Within a single run only; cross-run filtering needs the seen store
(Backlog item 1).

**Every record gains a `sources` list.** Collapsing duplicates would otherwise
destroy the one thing Task 10 calls trending — the same story arriving through
several independent sources on the same day. Source *names* are collected, not
counted, so a feed that lists its own post twice does not look like
corroboration.

`url_key()` decides what counts as the same article: scheme dropped so http
and https collapse, `www.` and a trailing slash dropped, `utm_*` and other
tracking parameters removed, the rest sorted so parameter order stops
mattering. It is safe to be this aggressive because the key is only ever a
dictionary key — the record keeps the URL it arrived with, so nothing here can
damage a link we later publish.

Merging fills gaps rather than overwriting, so a feed's date can rescue a
search result that arrived without one. `metadata_score()` ranks candidates by
scarcity, not size: a date outranks a longer snippet, because it is the one
field nothing downstream can reconstruct. Two fields merge generously — an
item claimed by any competitor source stays a competitor item, and one found
by both a hand-picked feed and a broad search term is judged by the looser
threshold. Some source vouched for it, and triage can only drop things.

First real run: 47 collected, 45 unique. One Hacker News thread arrived from
two different search terms and is now marked `x2`; one Camunda post the feed
listed twice collapsed without a mark, which is the distinction working.

Worth noting for Backlog item 10: two search terms returned 9 and 7 results on
one run and 0 on another the same afternoon. Kagi's recency window is not
stable minute to minute, so term-usefulness figures need several runs before
they mean anything.

### Task 8: Triage — done
`triage()`: one `TRIAGE_MODEL` call over all titles and snippets, scoring each
0-5 against SpiffWorks' space. Keeps everything at or above
`TRIAGE_THRESHOLD`, sorts by score then recency, and returns the top
`MAX_ARTICLES`. The cap is what keeps a run cheap — it decides how many pages
Task 9 extracts and how much text reaches synthesize.

The prompt spends most of its words on what a **0** looks like, not a 5. The
list arrives from broad searches and a Hacker News feed, so most of it really
is unrelated, and a scorer that has not been told to expect that grades on a
curve. It also says to judge only what the title and snippet actually claim:
guessing at what a page might contain is how a report fills with marketing
copy.

An item the model skips scores 0 rather than passing through unjudged, and a
malformed row is dropped without ending the run — one bad row must not cost us
the other forty. A count mismatch is printed.

**The scale started at 0-3 and was widened to 0-5 after the first run.** On
the narrow scale, 83 items scored 2/14/31/36 across 3-2-1-0: sixteen cleared a
threshold of 2, ten places were available, and the six that lost were cut by
recency rather than merit — a fresh Instagram reel displaced older items
scoring the same. The problem was resolution, not the threshold. Four values
cannot rank fourteen items.

On the wider scale a comparable run scored 75 items 0/1/6/11/15/42 across
5-4-3-2-1-0. Seven cleared a threshold of 3, the cap stopped binding
altogether, and the reel scored itself out. `TRIAGE_THRESHOLDS` moved with it:
loose/normal/strict are now 2/3/4.

What still gets through at 3: a vendor's "digital worker factory" landing
page, a blog *category* listing, a patents gazette index. The scorer is
reading a plausible title and a plausible snippet and cannot tell that the
page behind them is not an article. Task 9 extracts these before anything
reads them, so the cost is one wasted extract each — worth watching, not worth
fixing before the digest step (Backlog item 6) exists to notice it.

### Task 9: Extract survivors — done
`extract_articles()`: one batched Kagi extract for the survivors, then
`truncate()` cuts each page to `ARTICLE_CHAR_BUDGET` before the text goes
anywhere near synthesize. Extract output runs to tens of thousands of
characters — one page today came back at 44,785. The cut lands on a line break
where there is one nearby and appends `[truncated]`, because a paragraph
stopping mid-sentence with no explanation reads like a fact.

Results are matched to items **by normalized URL, not by position**. Kagi
echoes each URL back, sometimes redirected, and a silently misaligned zip
would attach one article's text to another article's title — a failure that
would never look like a failure. `url_key()` from Task 7 does the matching.

Items whose page cannot be read are dropped rather than carried forward empty.
A title with no text behind it is what fills a report with confident sentences
about pages nobody read.

**One URL can poison a whole batch.** This cost a full run before it was
understood. Kagi normally reports an unreadable page in that page's own
`error` field, which is why Task 2 concluded one dead link cannot cost us the
other nine. That is not always true: some URLs make it answer the *entire*
batch with `data: null` — HTTP 200, no envelope error, nothing at all. Ten
items in, zero out, and the run printed a plausible-looking empty result.

Two confirmed poisoners, both of which our own collectors produce routinely:

- `airhacks.fm/episodes/feed.xml` — a feed URL returned by search
- `news.ycombinator.com/item?id=...` — an HN discussion page

An Instagram reel, by contrast, extracts fine, and a blog category page
returns a normal per-page empty. So this is not "unusual URLs fail"; there is
no pattern worth blacklisting, and a blacklist would rot.

`extract_batch()` handles it generically: when a batch returns fewer results
than URLs, ask again one URL at a time. That costs a handful of extra calls on
the days it happens, names the offender in the log, and keeps one bad link
from costing the other nine. It fired on the very next run and saved seven
articles. It also makes open question 1 sharper — a bad day could now mean
eleven extract calls instead of one.

First clean run: **7 of 10 pages readable.** Two SAP community pages refused
the crawler, and the HN item page was the poisoner.

### Task 10: Synthesize — done
`synthesize()`: one `SYNTHESIZE_MODEL` call over every surviving article at
once, returning draft Markdown. `article_block()` gives each article a header —
URL, publication date, the sources that found it, its triage score — and then
its truncated text.

**One call, not one per article.** The whole job here is seeing the day as a
whole: what groups with what, and what turned up twice. Neither is visible from
inside a single article. A per-article step that keeps breadth up without
sending this much raw text is Backlog item 6; today six articles reach the call
as 37K characters, which is affordable.

**The header names the sources rather than counting them.** That is what lets
the model say *why* it called something trending, and it paid off on the first
run in a way a count would not have. Two of the six articles were the same
Newgen press release, syndicated to PR Newswire and the Manila Times under
different URLs, so dedupe (Task 7) correctly left them as two records. The
draft grouped them and said what they were: one source, two placements, "not a
trend". Meanwhile it called the Camunda post trending and named the three
sources that found it. A count of `x2` would have made the syndication look
exactly like the corroboration.

**The prompt asks it to invent the groups from the day's articles**, rather
than filling in a fixed list of headings. A standing list produces empty
sections on quiet days and forces unrelated items together on busy ones. The
four categories from `# Purpose` — breaking news, events, speaking
opportunities, popular blog posts — are given as an ordering rule instead:
lead with them when the day produces one.

Two rules exist to keep the report honest about thin material, and both fired
on the first run. The UiPath page Task 8 let through came back as sidebar
navigation with no article body, and the draft said so — one flagged line, no
invented detail. And because `truncate()` leaves a visible `[truncated]`
marker, the draft could report that the Camunda experiment's second example was
cut off rather than describing a result it never saw. The marker Task 9 added
for the reader turns out to matter more for the model.

**Length and tone are set here, not in the copy edit.** The first version of
this prompt asked for a good report and got a verbose, admiring one: 7,460
characters over six articles, full of the report's opinion of its own contents
— "the day's one substantive engineering read", "the two divergences are the
interesting part", "worth quoting back at anyone claiming", "useful mainly as a
read on how the mid-market is being sold to".

Fixing that in Task 11 was tried first and does not work. An editor forbidden
to change facts can only cut the framing around them, so a copy edit told to
halve the report cut 12% and left the shape intact. Deciding a report is a
ten-minute read, and that it states facts rather than admiring them, is a
decision about what to write. It has to happen here.

So the prompt now names the reader's ten minutes as the size of the report,
lists the frames that are banned outright, and sets two budgets that bind: the
paragraph under a `##` heading is three sentences, and a bullet is one or two.
Prose budgets work where "be succinct" does not, because a model can check
itself against them.

`max_tokens` is 16000 rather than the default. Opus thinks by default and the
budget covers thinking and reply together, so a tight one truncates the report
instead of shortening it.

An empty list returns a "nothing to report" stub without calling the model.

Runs: 6 articles (37K characters) to a 7,460-character draft under the first
prompt; 8 articles (49K characters) to a 6,273-character draft under the
current one. A larger input now produces a shorter report.

### Task 11: Copy edit — done
`copy_edit()`: a second call over the draft applying Strunk and White. Style
only — it introduces no claims and drops no citations.

Succinctness and a factual voice were tried here first and moved to Task 10.
This step edits prose it may not change the meaning of, so it can cut a frame
but never the sentence a frame was wrapped around. See Task 10 for what that
cost and why the requirement belongs upstream.

The prompt lists the rules from *The Elements of Style* worth naming — omit
needless words, active voice, positive form, concrete language, no qualifiers,
parallel construction in a bullet list, the emphatic word last — then the hard
limits: change no fact, never edit inside quotation marks, keep every `##`
section in order, and keep every link pointing where it pointed.

**Links are checked rather than trusted.** `find_urls()` compares the draft
against the edit, and an edit that lost a link is thrown away in favour of the
draft. A dropped citation is the one failure here that reads perfectly — the
edited paragraph looks fine, and the claim it makes simply has nothing behind
it any more. The draft is already publishable, so no sentence is worth a
source. It has not fired yet.

**The edit is now nearly a no-op, and that is the result.** On the first run
after the split it returned 6,242 characters from a 6,273-character draft, all
8 links intact. Strunk and White has little to do to prose that was written
tight and factual to begin with. The size of this step's diff is a useful
reading of the synthesize prompt: a large one means Task 10 has drifted back
into writing that needs saving. The step stays either way — Constraint 1
requires a copy edit pass on anything that reaches the user.

### Task 12: Render — done
`render()` writes `reports/YYYY-MM-DD.md`: a title, the edited body, then
References. It returns the path, and `main()` prints both the file and where it
went.

**One file per day, overwritten on a re-run** rather than appended to. Running
twice in an afternoon should leave one report, not two halves of one. That is
also most of what Backlog item 14 means by an idempotent run.

**The title is added here, not asked for from the model.** Synthesize is told
not to write one, because the model does not know the date the run happened on
and would date the report from whatever the articles said.

**References** are what Constraint 4 asks for by name: every item the report
links to, with its title, publisher, publication time and URL. `references()`
builds the list from the item records rather than from the body, since the body
carries only a link and whatever the sentence called it, while the record still
holds the title as published and the time. Matching is by `url_key()`, so a
link the writing step reproduced with a tracking parameter still finds its
item, and an article that was read but never cited is left out and counted in
the log.

The publisher is the URL's host, not `source_name`. A feed's `source_name` is
its publisher, but a search result's is the query that found it, and "Business
process automation" listed as the source of a PR Newswire release is a search
term wearing a publisher's clothes.

**The times in References are not all publication times.** Search results carry
timestamps that are `now` minus a whole number of hours: one run returned
09:01:25, 08:01:26, 07:01:26 and 01:01:26, and the next returned the same
pattern on `:42`, each matching the clock time of the run. Kagi renders a
relative age — "2 hours ago" — as an ISO timestamp at query time. Feed dates
are real; the Camunda entry came back as 20:09:00+00:00 and stayed there across
runs. So a search-sourced reference time is accurate to the hour of *age*, not
to the moment of publication, and Backlog item 4 is what would fix it.

### Task 13: Check-in — removed
It was a prompt printed after the report asking for feedback, and the feedback
happens in conversation anyway. `main()` ends by naming the file it wrote.
Turning that feedback into edits is still manual, and still Backlog item 12.

## Definition of done

`uv run main.py` runs from a clean shell and writes a report to `reports/` that
cites real sources with real links. **Met** — see `reports/2026-08-10.md`.

---

# Part 2 — Backlog

Ordered roughly by expected value, not by dependency. Each item names the MVP
shortcut it removes.

## Next — the shortcuts that will bite first

1. **State store (`state.py`, `seen.json`).** URL → first-seen date and title,
   with `is_new(url)` and `mark_seen(item)`. This is what makes "new articles"
   and "major announcements" mean anything across runs; without it every run
   re-reports the same Gartner item. Items dropped at triage get marked seen so
   they don't resurface. *Removes: no state, no history.*
2. **Per-source triage thresholds.** Loose for substacks and competitors
   (hand-picked, presumed interesting), normal for search results, strict for
   HN frontpage and the analyst newsrooms (broad and mostly noise).
   *Removes: one threshold.*
3. **Error containment.** Kagi errors return `None` and log; a failing source or
   a failing extract skips rather than ending the run. *Removes: crash on
   failure.*
4. **Publication-date resolution.** When the feed and search result give
   nothing, look for `article:published_time`, a `<time>` element, or JSON-LD
   `datePublished`. Fall back to "date unknown" rather than guessing — a wrong
   date is worse than an absent one. *Removes: free dates only.*
5. **Raise or remove the 10-item cap,** once we know what a real day's volume
   looks like.

## Then — quality of the report

6. **Digest step.** One cheap-model call per page producing a compact record:
   two or three sentences on what is new, a category (`news`, `event`,
   `speaking_opportunity`, `blog_post`, `product_announcement`, `company_news`,
   `analysis`), one or two verbatim quotes for grounding, and the date and URL
   carried through. Written per page so each call stays small and each failure
   is isolated. Only digests reach the synthesize call, which keeps breadth high
   without burying the writing step in raw article text. *Removes: no digest.*
7. **Competitor section.** Its own section, ordered by significance rather than
   filtered by it. Material changes lead — releases, funding, acquisitions,
   partnerships, pricing or licensing changes, leadership moves, customer wins.
   Everything else follows as a short list of what they published, which over
   time reads as a picture of where each company is putting its attention.

   The reasoning behind this: **triage decides what we read, not what matters.**
   A competitor's technical post is valuable for reasons unrelated to whether it
   is news — it shows what they're building, how they teach the problem, which
   integrations they're promoting, what positioning they're testing. Suppressing
   routine posts to isolate announcements discards most of that signal. So
   nothing on the competitor pages is filtered for being ordinary; prominence is
   the synthesize step's call, not triage's, which can only drop things.

   **Camunda is currently the only competitor source.** Appian and Pega left
   with the index-page collector (Task 6) because neither publishes a feed, so
   a competitor section built today would be a Camunda section. Item 19 is the
   way back in, and it comes before this one in practice even though it sits
   later in the list.
8. **Report length target.** Uncapped for now. Set one after a few real runs.

## Then — the feedback loop

9. **Per-run metrics.** `runs/YYYY-MM-DD.json` with per-step counts and timings.
   Prerequisite for the next two items.
10. **Search-term usefulness.** Per term: results returned, how many cleared
    triage, how many reached the report. Terms producing nothing over several
    runs are flagged for removal; recurring topics no term is catching are
    flagged as candidate additions. Appended to the report. *Satisfies
    Constraint 2.*
11. **Lens recommendation.** Review whether results skewed off-topic and suggest
    a lens change **per term**, since that is where lenses are set. Weekly, not
    daily — one run isn't enough signal.
12. **Apply feedback automatically.** Turn my feedback into proposed edits to
    the source lists in `config.py`, AGENTS.md, and SOURCES.md, for approval
    before writing.
    *Removes: manual check-in.*
13. **SOURCES.md.** The curated source list named in `# Purpose`, once we have
    enough runs to know which sources earn a place.

## Then — operations

14. **Scheduling.** Daily cron. Re-running a day already overwrites that day's
    file rather than duplicating it, so what remains is the schedule itself
    and somewhere for the output to go that nobody has to be watching — item
    18's delivery channel.
15. **`--dry-run`.** Collect and triage but make no extract or LLM calls, for
    testing changes to the source lists without spending anything.
16. **Real logging.** Per-step counts and timings to a log file.
17. **Second LLM provider.** `llm.py` grows a provider branch when we actually
    want to send a task somewhere other than Claude, as `# LLM` allows.
18. **Report delivery.** Email or another channel. Needs one more credential.
19. **A route back for sources with no feed.** Appian and Pega left with the
    index-page collector. Whatever brings them back has to supply a
    publication date, or it repeats the problem that removed the collector:
    per-site selectors that read the date off the listing, a headless browser,
    or Backlog item 4 applied to bare URLs. Worth doing only once the
    competitor section (item 7) is real enough to feel the gap.

---

## Open questions

1. **Kagi per-call cost and quota.** Task 0 confirmed the key works for both
   search and extract. What one search and one 10-URL extract actually cost,
   and whether there's a daily cap, is still unknown — worth checking at
   kagi.com/api/billing before the agent runs unattended on a cron.
2. **Analyst-site terms of use** — mostly settled by Task 6. Gartner's
   robots.txt allows `/en/newsroom`; their CDN blocks the crawler anyway, so
   the site arrives through search. Forrester and HFS are now read through
   their own published feeds, which is as clear a permission as a site gives.
   Nothing here is scraped any more, so the question that remains is only
   whether Task 9 may extract the article bodies those feeds point at.
3. **Competitor feeds** — answered. Camunda publishes RSS and is in `FEEDS`.
   Appian and Pega publish none: `/feed`, `/rss.xml`, `/blog/feed` and
   `/blog/rss.xml` were all tried against both, and all returned nothing. That
   is what dropped them; see Backlog item 19. 
"""Settings and secrets. Every other module imports this one.

Importing this module loads `.env`, so the keys are available no matter which
directory you run from. Nothing here reaches the network.
"""

import os
from pathlib import Path

HERE = Path(__file__).parent


def load_env():
    """Read `.env` from this directory into the environment.

    Values already set in the real environment win, so
    `KAGI_KEY=... uv run main.py` overrides the file.
    """
    env_file = HERE / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env()


# --- Secrets -----------------------------------------------------------------
# Empty rather than missing if unset; main() checks them at startup so the
# failure is one clear line instead of a KeyError somewhere in the pipeline.

KAGI_KEY = os.environ.get("KAGI_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


# --- Kagi --------------------------------------------------------------------

KAGI_API = "https://kagi.com/api/v1"

# How far back search results may have been published or updated, in days.
# The agent runs daily, so 1 keeps each run to what is actually new. None
# means no limit.
#
# Kagi filters on a whole date, not a timestamp, so 1 means "since the start
# of yesterday" — between 24 and 48 hours back depending on the hour the run
# starts. Erring long is deliberate: a morning run limited to today's date
# would miss everything published yesterday afternoon.
#
# Applies to search only. Feeds have their own window (FEED_WINDOW_DAYS) and
# index pages have none.
SEARCH_WINDOW_DAYS = 1

# Kagi's extract endpoint takes at most 10 URLs per call. Triage caps the day's
# reading at MAX_ARTICLES, so keeping these equal means one extract call.
KAGI_EXTRACT_LIMIT = 10


# --- Models ------------------------------------------------------------------
# The per-task assignment from the LLM table in AGENTS.md. All swappable; these
# are starting points, not commitments.

TRIAGE_MODEL = "claude-haiku-4-5"
SYNTHESIZE_MODEL = "claude-opus-4-6"
COPY_EDIT_MODEL = "claude-sonnet-4-6"


# --- Prompts -----------------------------------------------------------------
# The wording each LLM task runs on. Kept here rather than in main.py so the
# behavior of a run — what "worth reporting" means, what the report reads
# like, what a copy edit is allowed to touch — can be tuned without editing
# code. main.py only calls .format() on these; it holds no prompt text itself.

TRIAGE_PROMPT = """\
You are screening today's reading for SpiffWorks, a company working on BPMN
workflow orchestration and process automation. We care about: BPM and BPMN,
workflow and orchestration engines, process automation, AI agents doing real
work in businesses, and the vendors and analysts in that market. We also want
breaking news, conferences and events, speaking opportunities, and blog posts
people are actually reading.

Score each item 0 to 5 for how much it deserves a place in today's report:

  5 — a real development in our space: a release, a finding, a shift
  4 — an event, conference or call for speakers
  3 — articles, research studies, and blog posts not directly published by a vendor
  2 — tangential articles, research and blog posts
  1 — only glancingly related, or a vendor describing its own product
  0 — unrelated, or an advert, job post, or forum question with no content

Use the whole range. A score of 4 or 5 says we would notice its absence from
the report; if fifteen items score 4, none of them did.

Judge only what the title and snippet actually say. Items reached us through
broad searches and a Hacker News feed, so most of this list is genuinely a 0.

Reply with a JSON list of {count} objects, one per item, and nothing else:

[{{"id": 1, "score": 0}}]

--- items ---
{items}
"""

SYNTHESIZE_PROMPT = """\
You are writing today's research report for SpiffWorks, a company working on
BPMN workflow orchestration and process automation. The reader works for SpiffWorks.
They know the field, have three minutes, and want to know what happened today
that they would otherwise have missed.

**Three minutes is the size of the report**, not an aspiration. Write to it.

Below is every article that survived today's screening. It is a day's harvest
from broad searches and a handful of feeds, so some of it is thin. That is
expected. Report what is here.

**Long pages arrive cut short.** We keep the first few thousand characters of
each page and mark the cut `[truncated]`. That is our budget, not the author
stopping mid-sentence, and the reader knows it already. Never mention it —
"the post breaks off", "truncated mid-list", "we do not have the rest" are all
noise. Simply report what the text you were given establishes, and claim
nothing about what the rest of the page said.

Write the report in Markdown. Do not add a title, a preamble, or a closing
summary — a title and a References section are added afterwards.

Summarize each article provided. **The `##` heading is the article's title as
a link: `## [Article title](its url)`.** The URL is given with each article
below; copy it exactly. That link is the only record of where the article came
from, so a heading without one is a summary the reader cannot check, and it
drops the article from the References section.

Follow the heading with the source, author and a date if available.
Lead with an overall summary of the article in plain english.  Be direct and factual.
If there are major points in the article, summerize these with bullet points.

Rules:

  - **Only what the articles say.** No background you happen to know, no
    inference dressed as fact.
  - **State facts, not observations.** Report what an article says, not how
    interesting it was to read.
  - **Say when something is vendor related.** "A vendor's product page, no detail behind
    the announcement" is a fact about the source and belongs in the report.
  - **Dates.** Give an article's publication date when you place it in time.
    Some read "date unknown"; say that rather than guessing.

Two budgets, and they bind:

  - An article summary is 2 sentences.
  - A bullet is one sentence.

--- articles ---

{articles}
"""

COPY_EDIT_PROMPT = """\
Copy edit the Markdown report below, applying Strunk and White's *The Elements
of Style*. Reply with the edited report and nothing else — no preamble, no
notes on what you changed.

Edit for these, in roughly this order of value:

  - **Omit needless words.** Every sentence carries its own weight or goes.
    "The fact that", "in order to", "it should be noted that" are always
    deletable.
  - **Use the active voice**, and prefer nouns and verbs to adjectives and
    adverbs.
  - **Put statements in positive form.** Say what something is, not what it
    is not.
  - **Use definite, specific, concrete language.** Prefer the particular to
    the general.
  - **Cut qualifiers** — very, rather, quite, somewhat, arguably, essentially.
    They weaken what they modify.
  - **Express coordinate ideas in similar form**, especially inside one bullet
    list.
  - **Put the emphatic word at the end of the sentence.**
  - **Keep related words together**, and keep one paragraph to one topic.

You are editing style, not substance. These are hard limits:

  - **Change no facts.** Not a number, a name, a date, a company, or a claim.
    Add nothing the draft does not already say, however sure of it you are.
  - **Keep every item.** Compressing an article's coverage never means
    deleting it. Every `[text](url)` in the draft appears in your reply,
    pointing at the same URL; you may reword the link text. A lost link costs
    a citation, which is worse than any sentence you could improve.
  - **Never edit inside quotation marks.** Quoted text is verbatim from a
    source. Fix the sentence around it instead.
  - **Keep the structure**: the same `##` sections in the same order, and a
    bullet stays a bullet. Section headings may be tightened.
  - **Provenance is fact.** "Found by three independent sources", "no detail
    behind the announcement", "no independent reporting behind either
    placement", "date unknown" — these say how far to trust a line. They are
    the most factual sentences in the report. Keep them, shortened.

--- report ---

{draft}
"""


# --- Tuning ------------------------------------------------------------------

# How many results to keep from each search term.
SEARCH_RESULTS_PER_TERM = 10

# How far back a feed entry can be published and still count as new. Without a
# seen-URL store (Backlog item 1), this window is the only thing keeping the
# MVP from re-reporting the same posts every run.
FEED_WINDOW_DAYS = 2

# How far ahead an event can be and still count as "upcoming". Event feeds run
# the same date backward from now for FEED_WINDOW_DAYS, so this is a second,
# forward-looking window rather than a reuse of it.
EVENT_WINDOW_DAYS = 14

# Hard cap on how many events reach the report, after triage. Kept separate
# from MAX_ARTICLES because it isn't tied to KAGI_EXTRACT_LIMIT — events are
# never extracted.
MAX_EVENTS = 8

# Characters of snippet kept per item. Kagi's search snippets are already
# short; feed summaries are not, and triage reads every one of them in a
# single call.
SNIPPET_CHARS = 400

# Triage keeps items scoring at or above this, on a 0-5 scale. One threshold
# for every source in the MVP; per-source gates are Backlog item 2.
#
# The scale started at 0-3 and was widened because too many items landed on
# the same number: with fourteen tied at one score and ten places to fill,
# the cap was choosing by recency rather than by merit.
TRIAGE_THRESHOLD = 3

# Hard cap on how many articles we extract and read per run. This is the main
# thing keeping a run cheap and fast.
MAX_ARTICLES = 10

# Characters of extracted Markdown kept per article. Task 0 measured a single
# Wikipedia page at 98K characters, so this cap is doing real work.
ARTICLE_CHAR_BUDGET = 6000


# --- Sources -----------------------------------------------------------------
# What to research. Grouped by collector, so each list feeds exactly one step
# of the pipeline: SEARCH_TERMS -> Task 4, FEEDS -> Task 5.
#
# A source has to arrive by search or by feed. There is no third collector:
# scraping listing pages was tried and removed, because a page gives us no
# dates and no way to tell this morning's post from a six-week-old one. See
# Task 6 in AGENTS.md.
#
# Every entry in both lists carries a `threshold` recording how hard that
# source should be to get past triage. The MVP ignores it and gates everything
# on TRIAGE_THRESHOLD above; Backlog item 2 switches to these per-source
# values, and the judgment is recorded here now so that change needs no edits
# to this data.
#
# `group` is for the report rather than the pipeline — "competitor" items get
# their own section (Backlog item 7).

# One Kagi search each, restricted to the last SEARCH_WINDOW_DAYS days.
#
# Thresholds vary by how precise the term is, not by how much we care about
# the subject. A narrow term returns few enough results that most are worth a
# look; a broad one returns mostly marketing copy that happens to use the
# words. These are opening guesses — Backlog item 10 measures how each term
# actually performs and tells us which to move.
#
# A term may also carry an optional "lens": either a built-in lens identifier
# or the ID from https://kagi.com/settings/lenses when a lens is shareable.
# Lenses belong here rather than on the whole run, because the right lens
# depends on the term — a broad industry phrase wants a narrowing lens that
# would throw away most of what a precise term is looking for. None are set
# yet; Backlog item 11 recommends them once there is run data to judge from.
#
#     {"term": "Business Analytics", "threshold": "strict", "lens": "..."},
#
# An optional "name" is what the report calls the term. The term itself reads
# fine for a plain phrase, so only a term that is really a stand-in for a
# source needs one — a site: query, for instance.
SEARCH_TERMS = [
    # Narrow and on-target. Low volume, so take nearly all of it.
    {"term": '"workflow orchestration"', "threshold": "loose", "lens":"forums"},
    {"term": '"workflow orchestration"', "threshold": "strict", "lens":"blogs"},
    # Specific enough to trust, broad enough to want filtering.
    {"term": "Python AI", "threshold": "normal", "lens":"forums"},
    {"term": "Python AI", "threshold": "normal", "lens":"blogs"},
    {"term": "Business process automation", "threshold": "strict", "lens":"forums"},
    {"term": "Business process automation", "threshold": "strict", "lens":"blogs"},
    # Broad industry phrases. Mostly vendor marketing that happens to match.
    {"term": '"AI BPM"', "threshold": "strict", "lens":"forums"},
    {"term": '"AI BPM"', "threshold": "strict", "lens":"blogs"},
    # A site: query standing in for a listing page we cannot extract. Gartner's
    # robots.txt allows /en/newsroom, but their CDN challenges any client that
    # is not a browser, so Kagi's crawler comes back empty. Kagi's *index* has
    # the pages, so search reaches what extract cannot: titles, snippets and
    # dates, but no full article text.
    {"term": "site:gartner.com/en/newsroom", "name": "Gartner", "threshold": "strict"},
]

# RSS and Atom feeds. Publication dates come free here, which is what lets us
# tell new from old, so a source without a feed has to come in through search
# instead. Substacks serve RSS at /feed; for everyone else, try /feed/, /rss,
# and /blogs/feed/ before giving up.
FEEDS = [
    {
        "name": "Berkeley RDI",
        "url": "https://berkeleyrdi.substack.com/feed",
        "threshold": "loose",  # hand-picked, so new posts are presumed interesting
    },
    {
        "name": "AI Agents Simplified",
        "url": "https://aiagentssimplified.substack.com/feed",
        "threshold": "loose",
    },
    {
        "name": "Oliver Patel",
        "url": "https://oliverpatel.substack.com/feed",
        "threshold": "loose",
    },
    {
        "name": "AI Maker",
        "url": "https://aimaker.substack.com/feed",
        "threshold": "loose",
    },
    {
        "name": "Camunda",
        "url": "https://camunda.com/feed/",
        "group": "competitor",
        "threshold": "loose",
    },
    {
        "name": "Hacker News front page",
        "url": "https://hnrss.org/frontpage",
        "threshold": "strict",  # very broad, mostly noise
    },
    # Analysts. Both publish a feed; neither advertises it on the page we were
    # scraping before. Forrester's feed is their analyst blogs rather than the
    # press newsroom — commentary instead of announcements, and the better read
    # of the two.
    {
        "name": "Forrester",
        "url": "https://www.forrester.com/blogs/feed/",
        "threshold": "strict",  # trusted, but broad
    },
    {
        "name": "HFS Research",
        "url": "https://www.hfsresearch.com/feed/",
        "threshold": "strict",
    },
]

# RSS feeds of upcoming events rather than posts. Collected and triaged like
# FEEDS, but on a forward-looking date window (EVENT_WINDOW_DAYS) since the
# date on each entry is when the event happens, not when it was published.
# Reported in their own section rather than folded into the synthesized body.
EVENT_FEEDS = [
    {
        "name": "DC Tech Events",
        "url": "https://dctech.events/events-feed.xml",
        "threshold": "loose",  # These are nearby technology events in DC and are likely to be of interest.
    }
]

# Appian and Pega used to sit in a third list, scraped as listing pages.
# Neither publishes a feed at any path worth guessing, so removing that
# collector removed them, and Camunda is the only competitor left. Getting
# them back means a site: term here that works — see Backlog item 7.

# What each threshold name costs, on triage's 0-5 scale. The names above say
# how a source should be judged; these numbers say what that means.
TRIAGE_THRESHOLDS = {"loose": 2, "normal": 3, "strict": 4}


# --- Paths -------------------------------------------------------------------

# Where the day's report is written, one file per day as YYYY-MM-DD.md. Created
# on the first run. Re-running a day overwrites that day's file rather than
# adding to it, which is what keeps a repeated run harmless.
REPORTS_DIR = HERE / "reports"

# Cross-run memory of which URLs we've already reported on. state.py owns
# reading and writing it; nothing else touches the file directly.
SEEN_FILE = HERE / "seen.json"

# Configuration

# --- Models ------------------------------------------------------------------
# Use these different models, depending on the task.
TRIAGE_MODEL = "claude-haiku-4-5"
SYNTHESIZE_MODEL = "claude-opus-4-6"
COPY_EDIT_MODEL = "claude-sonnet-4-6"


# --- Tuning ------------------------------------------------------------------

# How many results to keep from each search term.
SEARCH_RESULTS_PER_TERM = 10

# How far back a feed entry can be published and still count as new.
FEED_WINDOW_DAYS = 2

# Characters of snippet kept per item. Kagi's search snippets are already
# short; feed summaries are not
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
SEARCH_TERMS = [
    {"term": '"workflow orchestration"', "threshold": "loose", "lens":"forums"},
    {"term": '"workflow orchestration"', "threshold": "strict", "lens":"blogs"},
    {"term": "Python AI", "threshold": "normal", "lens":"forums"},
    {"term": "Python AI", "threshold": "normal", "lens":"blogs"},
    {"term": "Business process automation", "threshold": "strict", "lens":"forums"},
    {"term": "Business process automation", "threshold": "strict", "lens":"blogs"},
    {"term": '"AI BPM"', "threshold": "strict", "lens":"forums"},
    {"term": '"AI BPM"', "threshold": "strict", "lens":"blogs"},
    {"term": "site:gartner.com/en/newsroom", "name": "Gartner", "threshold": "strict"},
]

# RSS and Atom feeds.
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


EVENT_FEEDS = [
    {
        "name": "DC Tech Events",
        "url": "https://dctech.events/events-feed.xml",
        "threshold": "loose",  # These are nearby technology events in DC and are likely to be of interest.
    },

# Appian and Pega used to sit in a third list, scraped as listing pages.
# Neither publishes a feed at any path worth guessing, so removing that
# collector removed them, and Camunda is the only competitor left. Getting
# them back means a site: term here that works — see Backlog item 7.

# What each threshold name costs, on triage's 0-5 scale. The names above say
# how a source should be judged; these numbers say what that means.
TRIAGE_THRESHOLDS = {"loose": 2, "normal": 3, "strict": 4}



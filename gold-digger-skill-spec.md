# Build Spec — Gold Digger (`gold-digger`)

A personal Claude Code skill that scouts new dev tools/capabilities, ruthlessly filters noise, and helps you actually adopt the few that matter. It is an **anti-noise curator**, not a discovery feed.

> Name: **Gold Digger** (repo `gold-digger`). It digs through the firehose of noise and pulls out only the gold worth your attention.

---

## The one-line pitch

> Tell it "what's worth my attention?" and it either hands you 1–3 concrete moves (add this, drop that, here's how) — or tells you there's nothing this week. It is allowed, and expected, to say nothing.

---

## Core principles (THE NON-NEGOTIABLES — build the skill around these)

These are what make this different from every registry, newsletter, and feed that already exists. If the build drops these, it becomes just another feed.

1. **Silence is a first-class output.** If nothing clears the relevance bar, the correct answer is "Nothing worth moving this week. Your stack is clean." Do NOT manufacture a recommendation to seem useful. This directly fights the LLM failure mode of inventing problems where none exist (the "make this better" → fake errors trap).

2. **Subtraction over addition.** Recommending what to REMOVE (unused skills, redundant tools, dead dependencies) is as important as what to add. Most tools only do addition. This one prunes.

3. **The 15% rule.** When recommending a tool, never recommend "the whole tool." Identify the specific slice the user actually needs and present only that, with a concrete example wired to their context. ("You don't need all of X — you need feature Y, for your Z, like this.")

4. **Explicit, visible criteria.** Every recommendation must state WHY it passed the filter, in terms of the user's real context and ideally with a concrete benefit ("recommended because you use X in production and this cuts Y by ~Z%"). If it can't write that sentence with specifics, it doesn't recommend.

5. **Usage-based, not declaration-based.** Relevance is judged against what the user actually USES (files, installed skills/MCPs, recent git activity), not just what they say they care about.

6. **Calibration loop.** The user can flag a recommendation as a miss. Repeated misses on a topic → stop surfacing it. The skill trains against its own tendency to generate noise.

7. **Safety before adoption.** Community skills and MCP servers ship executable scripts that run on the user's machine — installing one is running untrusted code. Before ANY "ADD" recommendation for an installable skill/MCP, run a static safety review and surface the verdict. NEVER execute the thing being scanned; only read it statically. Be honest about limits: this flags red flags, it does not guarantee safety (a determined attacker can obfuscate). Framing the review as "first-pass red-flag detection, not a guarantee" is itself part of the trust pitch.

8. **Respect the cost of change (inertia bias).** A working workflow has value; disrupting it costs time and focus. "Better" is not the bar — "better by enough to justify the switch" is. Default to keeping the current setup. Recommend a change only when the gain clearly outweighs the migration/re-learning cost. This makes silence even more common and more trustworthy: most new things, even good ones, aren't worth the churn.

---

## Non-goals (state these so the build doesn't bloat)

- NOT a newsletter or scheduled digest (the passive-feed format is the exact problem being solved).
- NOT a comprehensive directory of all tools (registries already exist; abundance is the problem, not scarcity).
- NOT a chatbot that answers "is X good?" on demand (Claude chat already does that).
- NOT a multi-command CLI users must memorize. Keep the surface tiny.

---

## Interaction surface (keep it minimal)

Triggered by natural language, not memorized commands. Three intents, all phrasable in plain language:

| Intent | How the user invokes it | What happens |
|---|---|---|
| Review | "what's worth my attention", "anything new for me", "review my queue" | Runs scout + processes inbox + applies filter → returns 1–3 moves or silence |
| Capture | "consider this: <link>", or auto from the inbox bridge | Adds an item to the queue, extracts what tool/technique it is, scores later |
| Lateral (opt-in) | "think lateral about this", "non-obvious uses?" | The ONLY mode allowed to speculate. Looks for non-obvious fits across the user's other domains. Off by default. |

The default Review mode stays conservative (principle #1). Lateral mode is a deliberate, user-invited exception so the conservative discipline and the creative speculation don't contaminate each other.

---

## Architecture

### 1. User profile (`profile.yaml`)
Loaded on every invocation. Richer than just the repo. Set up once, edited anytime.
```yaml
identity:
  # Declare EVERY domain the user works in, not just dev. Each domain is a lens the scout and filter use.
  - dev: stack = [Next.js, Supabase, Claude API, Vercel]
  - founder/marketing: runs short-form video + paid ads business
  - other domains: [Roblox dev, ...]
workflows:
  # The concrete things the user does elsewhere, by hand. These are what connector recommendations target.
  - "runs Facebook/Instagram ad campaigns, checks analytics manually in Meta Ads Manager"
  - "creates image ads in a separate tool"
  - "edits short-form video"
current_focus:
  - "shipping X feature"
preferences:
  - language: es/en
  - bar: "only surface things that save measurable time"
muted_topics: []   # populated by the calibration loop
```

The `workflows` block is what powers cross-domain recommendations. If a workflow is "checks ad analytics manually in Meta Ads Manager," the scout/filter should be primed to surface a connector that brings that workflow into Claude (e.g., an official Facebook Ads MCP → see analytics by talking to Claude). Without declared workflows, the skill stays dev-only and misses the user's most valuable use cases.

### 2. Scout (`scripts/scout.py`)
Pulls from FREE sources, on invocation (not on a schedule). No paid APIs. **Sources must span ALL the user's declared domains, not just dev** — otherwise it never finds marketing/creative/ads tools.
- GitHub: trending + releases of repos in the user's stack (REST API, free token)
- Hacker News (Algolia API, free)
- Reddit relevant subs across each domain — dev subs AND marketing/ads/creative subs (public .json endpoints, free)
- Product Hunt (free tier) — covers marketing, design, video, and dev launches
- Official changelogs / RSS feeds for tools the user ALREADY uses (Anthropic, Vercel, Meta for Developers, the user's key libs and platforms) — this is how "new capability in something you already have" gets caught
- **Connector/MCP registries** (official MCP registry, GitHub MCP Registry, mcp.so, PulseMCP) filtered to the user's domains — this is how Facebook Ads MCP, Higgsfield-type connectors surface
- Claude Code's own `web_search` for live gaps, especially for non-dev domains where there's no clean RSS feed

Scout's job is to gather candidates. It does NOT decide relevance — that's the filter.

### 3. Inbox / queue (`queue.json`)
The mobile→desktop bridge. The user sees stuff on their phone; this is where it lands without friction.
- v1: paste links manually into a review.
- v1.5: a **Telegram bot** the user forwards anything to (one tap, share-sheet on iOS/Android). Free, no API review needed. Lands items in `queue.json`.
- v2: an Instagram/TikTok account friends can DM tool videos to (needs Meta Graph API review — defer).

### 4. Filter + scorer (the heart, in `SKILL.md` instructions + helper logic)
For each candidate (from scout or queue):
1. Extract its actual capabilities (parse docs / video transcript / README).
2. Score each capability against the profile + usage signal. Output a 0–100 relevance with the explicit reason sentence.
3. Apply the 15% rule: keep only the slice that matches; discard the rest.
4. **Net-benefit gate (switching-cost aware).** Relevance and "better than what I have" are NOT enough. Estimate the cost of adopting it — migration, re-learning, reconfiguring the workflow — and recommend ONLY if the gain clearly beats that disruption. Workflow churn is itself a cost; constant tool-switching is inefficient. Default bias is INERTIA: keep the current setup unless the upside is large and concrete. A marginal improvement that requires real migration → do not surface it. (`USE` recommendations — a new capability in a tool you already have — have near-zero switching cost, so they pass this gate easily; full workflow replacements have high cost and need a big win.)
5. Threshold: below the bar → archive silently. At/above → it's a "move."
6. Dedupe against what the user already has installed.

### 5. Output
Returns a **diff**, framed like commits on the user's setup, never a feed. There are FIVE recommendation types — each is a distinct line prefix so none gets buried:
```
+ ADD: <new external tool/skill>, only its <feature>, because <reason w/ specifics>. Wired to your case: <example>.
↑ USE: <capability the user already has but isn't using> — e.g. "Claude Code shipped /ultraplan; for your build flow it does X. Try it like this: <example>."
⇄ CONNECT: <connector/MCP> brings a workflow you already do by hand INTO Claude — e.g. "Official Facebook Ads MCP → check your campaign analytics by talking to Claude instead of opening Ads Manager." or "Higgsfield connects to Claude → generate your image ads in-conversation."
- DROP: <thing> — unused 90d, superseded by <thing you already have>.
~ NOTHING ELSE worth moving this week.
```
The `CONNECT` and `USE` types are the ones the dev-centric version would miss, and they're often the highest-value: `CONNECT` targets the user's real business workflows (ads, creative, analytics), `USE` unlocks free capability in tools already installed. Both must be driven by the profile's `workflows` and `identity` blocks.

If adopting: the skill produces the full integration plan (install/connect steps for their setup, where it fits, adapted usage example, what to remove to make room) — this is the unique value vs. a link.

### 6. Calibration (`misses.log`)
"That was a miss" → logged → topic decays in future scoring. Feeds `muted_topics`.

### 7. Safety scanner (`scripts/safety_scan.py`) — runs before any "ADD" of an installable skill/MCP
Statically reads the candidate's repo (never executes it) and flags red flags:
- Dangerous script patterns: `curl | bash`, `eval` of remote content, base64/obfuscated payloads, crypto-miner signatures, destructive commands (`rm -rf`), reverse shells.
- Exfiltration signals: reads of `~/.ssh`, env vars, credential/token files, browser data; network calls to unknown hosts.
- Lack-of-surprise check: does what the scripts DO match what the SKILL.md description SAYS? A "commit formatter" that phones home gets flagged.
- Requested permissions / `allowed-tools` review.
- Provenance: stars, repo age, author history; a 2-day-old repo with no history is a yellow flag.

Output a verdict — `safe` / `suspicious` / `dangerous` — with the exact lines that triggered each flag, plus the honest disclaimer that this is first-pass red-flag detection, not a guarantee. If `dangerous`, the ADD recommendation is withheld and the finding shown instead.

---

## File structure for Claude Code to build
```
gold-digger/
├── SKILL.md            # frontmatter + the principles + the filter/output logic
├── profile.yaml        # user profile (the user fills this once)
├── queue.json          # inbox items awaiting review
├── misses.log          # calibration feedback
├── scripts/
│   ├── scout.py        # gathers candidates from free sources
│   ├── score.py        # capability extraction + relevance scoring + 15% slicing
│   ├── safety_scan.py  # static red-flag review of installable skills/MCPs (never executes them)
│   └── telegram_in.py  # (v1.5) receives forwarded items into queue.json
└── references/
    └── sources.yaml    # the list of scout sources, editable
```

`SKILL.md` frontmatter `description` must clearly state the trigger so Claude Code loads it on phrases like "what's new for me / worth my attention / review my queue / consider this link."

---

## Build phases (ship v1 this weekend)
- **v1 (MVP, dogfoodable):** profile + scout + manual paste into review + filter with the discipline + diff output + integration plan. No Telegram yet. Fully local, fully free.
- **v1.5:** Telegram bot bridge → frictionless mobile capture into the queue.
- **v2:** Instagram/TikTok DM intake; multi-domain profiles; richer calibration.

---

## For the open-source repo (internship value)
- MIT license.
- README with: the problem (abundance, not scarcity), the principle that makes it different (silence as a feature), a 20-second demo GIF, one-command install.
- A short, honest "how the filter decides" section — transparency is the trust pitch.
- Don't oversell. The caveman playbook: specific problem, honest framing, dead-simple install.

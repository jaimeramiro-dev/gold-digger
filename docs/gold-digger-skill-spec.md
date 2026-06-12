# Build Spec — Gold Digger (`gold-digger`)

> **Mission:** Help any person optimize their business to the max with AI, software, and tools — whether just released or already out there — without a huge effort. Gold Digger removes the work of staying current.

A distributable, open-source Claude Code skill that scouts the whole ecosystem for new tools, skills, MCPs, connectors and capabilities, ruthlessly filters the noise, and helps each user adopt the few that actually matter for *their* work. It digs through the firehose and pulls out only the gold. It is an **adaptive anti-noise curator** — not a discovery feed, not a directory, not a personal config file.

---

## What it is — and what it is NOT

- It is a **product for many different users.** Nothing about any single user (stack, domains, hobbies, business) is hardcoded. The skill adapts to whoever installs it.
- It is **adaptive.** It learns each user's context three ways: (1) auto-detects their environment (their repo, installed skills/MCPs, files); (2) a short first-run onboarding; (3) responds to stated intent — "I want to start running paid ads" → it begins watching ad tools; if a user never mentions ads, it never surfaces them.
- It is NOT a newsletter or feed — that passive format IS the problem being solved.
- It is NOT a comprehensive directory — abundance is the problem, not scarcity.
- It is NOT a chatbot answering "is X good?" on demand — Claude already does that.
- It is NOT one person's config. The author ships smart defaults; the user never hand-picks sources.

---

## Core principles — a firm spine, flexible everywhere else

**The spine never bends:**
1. **Cut noise. Silence is a valid, expected output.** If nothing clears the bar, the answer is "Nothing worth your attention right now." NEVER manufacture a recommendation to seem useful. This fights the LLM instinct to invent value where none exists.
2. **Relevance to *this* person.** Judge candidates against what the user actually does and uses, not generic trendiness.
3. **Always give the honest why.** Every recommendation states the concrete reason it passed, in the user's own terms. If it can't write that sentence with specifics, it doesn't recommend.
4. **Safety before adoption.** (see Safety Scanner.)

**Everything else is a flexible default the skill reasons about per person — NOT a law:**
- **Slice vs whole tool:** usually surface only the relevant slice of a tool (you rarely need all 80 features), BUT recommend the whole tool when the whole tool is genuinely the right fit. Both are valid outputs.
- **Add vs remove:** no fixed hierarchy. For some users adding matters more; for others, pruning unused tools does. Decide per person and situation.
- **Switching cost:** weigh the disruption of changing a workflow against the gain. Bias toward keeping what works, but treat it as a factor, not an absolute rule.
- **Threshold:** adaptive per user, calibrated over time. Not a fixed number.

---

## How it adapts to each user

On first run, generate a per-user profile (NEVER ship one pre-filled):
- **Auto-detect:** read the user's repo, `~/.claude/skills/`, MCP config, package files, and recent git activity to infer their stack and what they actually use.
- **Onboarding (short):** ask the user, in plain language, their domains and what they want to keep an eye on (dev, marketing/ads, content, design, whatever they say).
- **Intent over time:** the user can tell it "I'm thinking of getting into X" and the scout starts covering X. Drop it and it stops.

The profile is data, generated per user. The skill's logic stays generic and adaptive.

---

## Architecture

### 1. Per-user profile (`profile.yaml`)
Generated on first run by auto-detect + onboarding. Holds the user's domains, declared workflows, current focus, language, and `muted_topics` (fed by calibration). Not authored by the developer; not shipped with anyone's data in it.

### 2. Scout (`scripts/scout.py`) — broad, living, primary-source-first
Pulls from a broad default source set covering the whole ecosystem, free to access. The user does NOT pick sources. The list lives in an editable config and is **living**: the skill can propose new high-signal sources over time and retire dead ones.

Source set (researched, free unless noted):
- **Primary release channels — highest signal.** Official blogs / changelogs / release pages of ALL the labs, not just the giants: Anthropic, OpenAI, Google, plus the long tail — DeepSeek, Meta, Mistral, Qwen, xAI, image/video generators, etc. RSS where available. This is where launches happen first, before any blog or reel reports them.
- **GitHub API** (free with a user-supplied token): trending, releases, topic tags — for new skills, tools, MCPs.
- **Connector / MCP registries:** official MCP registry, mcp.so, PulseMCP, Smithery — for new connectors and plugins, open source AND paid.
- **Skills registries:** skills.sh (Vercel `npx skills`), claudemarketplaces, anthropics/skills.
- **Hacker News** (Algolia API, free) — high signal for dev launches.
- **Product Hunt** (free tier) — kept but filtered hard; real signal (e.g. a major launch) buried in noise.
- **Reddit** (public JSON): relevant subs across the user's domains.
- **One daily newsletter** (e.g. TLDR AI) for compression, plus a depth source (e.g. Import AI). Used sparingly: the big AI newsletters overlap ~80% on the lead story, so more than one is redundant noise.
- **Bluesky** (free, open API) — the practical, free substitute for X, where much of the AI/dev crowd cross-posts.
- **X / Twitter:** NOT scraped or API-polled in v1 — its API is paid and restrictive, scraping breaks ToS. X content reaches the skill via the inbox or via Bluesky instead.

Scout gathers candidates; it does NOT decide relevance — the filter does.

### 3. Inbox / queue (`queue.json`)
The friction-killer for "I saw it on my phone." 
- v1: paste a link manually (any link — YouTube, X post, article, repo) and the skill evaluates it.
- v1.5: a Telegram bot the user forwards anything to in one tap.
- v2: an Instagram/TikTok account friends can DM tool videos to.

### 4. Filter + scorer (`scripts/score.py` + SKILL.md logic)
For each candidate:
1. Extract its actual capabilities (parse docs / README / transcript).
2. Score against the profile + usage signal; attach the explicit reason sentence.
3. Decide the form: relevant slice OR whole tool, per fit.
4. Net-benefit / switching-cost pass: recommend a change only when the gain clearly beats the disruption.
5. Cross-reference: confirm signal across multiple sources (HN + GitHub + a registry = real; a lone SEO blog = skip).
6. Threshold (adaptive): below the bar → archive silently; at/above → a "move."
7. Dedupe against what the user already has.

### 5. Output — five recommendation types, framed flexibly
Returns a **diff** on the user's setup, never a feed:
```
+ ADD: <tool/skill>, its <slice OR whole>, because <reason w/ specifics>. Wired to your case: <example>.
↑ USE: <capability you already have but aren't using> — e.g. "Claude Code shipped /ultraplan; for your build flow it does X."
⇄ CONNECT: <connector/MCP> brings a workflow you do by hand INTO Claude — e.g. "Meta Ads MCP → check campaign analytics by talking to Claude" / "Higgsfield → generate image ads in-conversation."
- DROP: <thing> — unused, redundant, or superseded by something you already have.
~ NOTHING worth moving right now.
```
On adopt: produce the full integration plan (install/connect steps for their setup, where it fits, adapted example, what to remove to make room). This is the value a link can't give.

### 6. Calibration (`misses.log`)
"That was a miss" → logged → the topic decays in future scoring → feeds `muted_topics`. The skill trains against its own tendency to over-surface.

### 7. Safety scanner (`scripts/safety_scan.py`) — before any ADD/CONNECT of something installable
- **Open source:** statically read the repo (NEVER execute it). Flag `curl|bash`, obfuscated/base64 payloads, credential/`~/.ssh`/env reads, calls to unknown hosts, destructive commands, miners. Check "lack of surprise": do the scripts match what the description claims?
- **Paid SaaS / connectors:** the check is about permissions and data — what scopes/access it requests, what it sends where.
- Verdict: `safe` / `suspicious` / `dangerous`, with the exact triggering lines, and an honest disclaimer: first-pass red-flag detection, NOT a guarantee. If `dangerous`, withhold the recommendation and show the finding instead.

---

## Why it beats "Claude just googles it" (the core problem it fixes)
1. **Primary sources, not SERPs.** It hits GitHub APIs, MCP registries and official changelogs — where launches actually appear — instead of SEO blogspam written about them later.
2. **The good prompt is baked in.** A skill IS a saved, optimized instruction set. The user says "what's gold for me?" in plain language; the rigorous scouting routine runs every time. No more depending on writing a perfect prompt each session.
3. **Cross-referencing.** Signal confirmed across multiple sources beats one shallow result.
4. **Same rigor every run** — quality doesn't depend on the user's energy that day.

---

## Cost model (important)
- Free to build, publish, and run. The skill is just files in a GitHub repo.
- **Each user runs it on their OWN Claude and their OWN credentials (their own GitHub token, etc.).** Other people's usage NEVER touches the author's account. It scales to any number of users at zero cost to the author.
- **Never embed the author's API key in the skill** — that would route everyone through the author's account (cost + security failure). Each user uses their own.
- The only non-free source is X (handled via inbox/Bluesky instead). Everything else — all lab blogs incl. DeepSeek/Meta, GitHub, HN, registries, Bluesky — is free.
- Scope covers open source AND paid tools; the filter judges by value to the user, not by license or price.

---

## File structure (Python)
```
gold-digger/
├── SKILL.md            # frontmatter + the spine principles + flexible defaults + filter/output logic
├── profile.yaml        # per-user, generated on first run (NOT shipped pre-filled)
├── queue.json          # inbox items awaiting review
├── misses.log          # calibration feedback
├── scripts/
│   ├── scout.py        # gathers candidates from the broad living source set (free sources)
│   ├── score.py        # capability extraction + relevance + slice/whole + net-benefit + cross-ref
│   └── safety_scan.py  # static red-flag review (OSS) + permissions check (paid); never executes scanned code
└── references/
    └── sources.yaml    # the living source list, editable; the skill can propose additions
```
Language: **Python** (best fit for fetch/parse/score and for statically analyzing other skills' code via `ast`). Output language: **100% English** (max reach).

`SKILL.md` `description` must trigger on plain phrasing like "what's new for me / worth my attention / what's gold / review my queue / consider this link."

---

## Build phases
- **v1 (MVP, dogfoodable):** per-user profile (auto-detect + onboarding) + broad scout + manual link intake + flexible filter + diff output + integration plan + safety scan. Local, free.
- **v1.5:** Telegram bot bridge for one-tap mobile capture.
- **v2:** Instagram/TikTok DM intake; richer multi-domain calibration.

## Open-source repo notes (adoption + portfolio value)
- License MIT. Output and docs in English.
- README leads with the **Mission**, then the problem (abundance, not scarcity), then the one thing that makes it different (silence as a feature; primary sources over blogspam). Add a 20-second demo GIF and a one-command install (`npx skills add <user>/gold-digger`). Position it as the curation + safety layer on top of `npx skills`. Don't oversell — the safety scan flags red flags, it doesn't guarantee safety.

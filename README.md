<p align="center">
  <img src="assets/logo.png" alt="Gold Digger" width="120">
</p>

<h1 align="center">Gold Digger</h1>

<p align="center">
  <img src="https://img.shields.io/github/stars/jaimeramiro-dev/gold-digger?style=flat&color=yellow">
  <img src="https://img.shields.io/github/last-commit/jaimeramiro-dev/gold-digger?style=flat">
  <img src="https://img.shields.io/github/license/jaimeramiro-dev/gold-digger?style=flat">
</p>

A thousand new tools, MCPs, and skills drop every week. You bookmark a dozen, install three, use none. Gold Digger reads the firehose for you and surfaces the one or two things actually worth your time — or tells you, honestly, that there's nothing today.

It's a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill. MIT, free to run. And yes, it's named Gold Digger because it's shamelessly only after the good stuff. No apologies.

[Install](#install) • [See it work](#see-it-work) • [Why it's not another feed](#why-its-not-another-feed) • [How the filter works](#how-the-filter-works)

---

## See it work

You ask. It digs. You get a short diff on your setup — what to add, what you already have but aren't using, what to drop. Every line carries the *reason*, in your terms:

```
> What's worth my attention?

  Checked 6 sources, 31 candidates. Kept 3.

  + ADD       Supabase MCP — you're on Postgres in this repo; this puts
              schema + queries inside Claude instead of a separate tab.

  ⇄ CONNECT   Stripe MCP — you were dealing with billing last week. Pulls
              your dashboard into Claude so you stop context-switching.

  ↑ USE       codegraph — already installed. The new `trace` command maps
              call paths; you've only ever used `search`.

  Curious what got cut? Ask "why'd you skip X?"
```

Real stars, ages, and benchmarks show up inline on each pick — copied verbatim from live data, never the round numbers I'd make up for a screenshot. That's why this README shows the shape of a run, not a staged one.

The part I'm actually proud of: when there's nothing good, it says so. No filler pick to look busy.

```
> What's worth my attention?

  ~ Nothing worth your attention right now.

  Looked at 34 candidates across 6 sources. A few were close, but none
  of them beat what you're already running.
```

A newsletter has to ship every week whether there's news or not. Gold Digger doesn't. Most weeks, silence is the honest answer — and that's the point.

## Why it's not another feed

Finding new tools was never the problem. The problem is that there are too many and 99% of them aren't for you. Feeds, newsletters, and "awesome-X" lists all make it worse — more to read, not less.

Gold Digger does the opposite:

- **It judges against *your* stack, not the timeline.** Every pick comes with a concrete reason tied to what you actually build. If it can't write that reason, it doesn't recommend. "Trending on Product Hunt" is not a reason.
- **It reads primary sources.** MCP registries, the GitHub API, lab changelogs, Hacker News — straight from where launches happen, not the SEO post written about them three days later.
- **The numbers are real.** Stars, age, benchmarks — copied verbatim from fetched data. Never inflated, never guessed. If it says 4k★, it's 4k★.
- **It scans before you install.** Any skill or MCP it recommends gets a static safety pass first — credential access, reverse shells, obfuscation. And it *shows* you what it found instead of hiding it, because heuristics throw false positives and the call should be yours.

## Install

The easy way:

```bash
npx skills add jaimeramiro-dev/gold-digger
```

The manual way:

```bash
git clone https://github.com/jaimeramiro-dev/gold-digger.git ~/.claude/skills/gold-digger
cd ~/.claude/skills/gold-digger && pip install -r requirements.txt
```

Dependencies are deliberately tiny: PyYAML and feedparser. Everything else is Python stdlib.

## First run

It auto-detects your environment and asks one short question about what else you work on — marketing, design, gaming, whatever. That's the whole setup. Your profile lives in `~/.claude/gold-digger/profile.yaml`, outside the skill folder, so reinstalling never wipes it.

Optional but recommended — a free GitHub token bumps your rate limit from 60 to 5,000 requests/hour:

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

## How to talk to it

Just talk to Claude normally:

| You say | It does |
| --- | --- |
| *"What's worth my attention?"* | Scouts, filters hard, hands back 1–3 moves or silence |
| *"Consider this: `<link>`"* | Saves a link to weigh on your next review |
| *"That was a miss"* | Recalibrates — that topic gets weighted down going forward |
| *"Think lateral about this"* | Speculative mode — looks for non-obvious cross-domain fits |

## Output format

Recommendations always come as a diff on your current setup:

```
+ ADD       <tool> — because <specific reason tied to your work>
↑ USE       <something you already have but aren't using>
⇄ CONNECT   <MCP/connector> brings a manual workflow into Claude
- DROP      <tool> — unused or superseded
~ Nothing worth your attention right now
```

## How the filter works

Two stages, on purpose — cheap first, expensive only on the survivors. Each user runs this on their own Claude, so the design keeps cost and time down.

```
  SCOUT            STAGE 1           STAGE 2           SAFETY           OUTPUT
  ─────            ───────           ───────           ──────           ──────
  ~30 candidates   metadata only,    relevance,        static scan      the diff,
  from MCP regs,   no tool calls     dedupe, and       on the final     or silence
  GitHub, HN,      ↓                 switching cost    1–3 only         ↓
  lab changelogs   ~30 → 8–10        ↓                 ↓                + ADD / ↑ USE
  (parallel)                         → 1–3             flags shown      ⇄ CONNECT / -
```

The scripts do the mechanical work — fetching, parsing, scoring. Claude makes the judgment call. That split is deliberate: deterministic where it should be deterministic, and a real opinion where it counts.

## Sources

**Layer 1 — ecosystem-wide:** Official MCP Registry, Glama, GitHub (topics `mcp-server`, `agent-skills`), Hacker News, Product Hunt, OSS Insight, Reddit. The MCP and connector registries are *the* channel for "X now connects to Claude."

**Layer 2 — per-tool, from your profile:** RSS feeds and GitHub releases for OpenAI, DeepMind, Anthropic, Meta AI, DeepSeek, and whatever's in your stack.

All free. No paid APIs. Each user runs on their own Claude with their own credentials — the creator's keys are never in the skill.

## Found gold?

If Gold Digger saved you a week of digging, a star helps other people find it. That's the whole ask.

## License

[MIT](LICENSE) — use it however you want.

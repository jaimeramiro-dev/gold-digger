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

[Install](#install) • [See it work](#see-it-work) • [Why it's not another feed](#why-its-not-another-feed) • [Why not just ask Claude?](#why-not-just-ask-claude)

---

## See it work

You ask. It digs. You get a short diff on your setup — what to add, what you already have but aren't using, what's established that you're missing. Every line carries the reason, in your terms:

```
> What's worth my attention?

  Checked 6 sources, 31 candidates. Kept 3.

  + ADD       Supabase MCP — you're on Postgres in this repo and half your
              recent commits touch raw SQL. Stop alt-tabbing to a client:
              this puts schema + queries inside Claude.

  ↑ USE       codegraph — already installed, but you only ever run `search`.
              The `trace` command maps call paths — the thing you've been
              doing by eye every time you touch this service.

  💡 KNOWN    Cursor — not new, just missing. Your last week was multi-file
              refactors done by hand. Verified live today — not pulled from
              stale training data.

  Curious what got cut? Ask "why'd you skip X?"
```

Real stars, ages, and dates show up inline on each pick — copied verbatim from live data, never the round numbers I'd make up for a screenshot. That's why this README shows the shape of a run, not a staged one.

The part I'm actually proud of: when there's nothing good, it says so. No filler pick to look busy.

```
> What's worth my attention?

  ~ Nothing worth your attention right now.

  Looked at 34 candidates across 6 sources. A few were close. None of
  them earned the swap.
```

A newsletter has to ship every week whether there's news or not. Gold Digger doesn't. Most weeks, silence is the honest answer — and that's the point.

## Why it's not another feed

Finding new tools was never the problem. The problem is that there are too many and 99% of them aren't for you. Feeds, newsletters, and "awesome-X" lists all make it worse — more to read, not less.

Gold Digger does the opposite:

- **It judges against *your* stack, not the timeline.** Every pick comes with a concrete reason tied to what you actually build. If it can't write that reason, it doesn't recommend. "Trending on Product Hunt" is not a reason.
- **It knows what's established, not just what's new.** A feed only shows this week. Gold Digger also flags the mature tool you're missing — and verifies it's alive before recommending, never from memory.
- **It checks the pulse.** Last push, archived status, real adoption — a repo with 2k stars that died last year doesn't get recommended on stars alone.
- **It reads primary sources.** MCP registries, the GitHub API, lab changelogs, Hacker News — straight from where launches happen, not the SEO post written three days later.
- **The numbers are real.** Stars, dates, benchmarks — copied verbatim from fetched data. If it says 4k★, it's 4k★.
- **It scans before you install.** Any skill or MCP it recommends gets a static safety pass first — credential access, reverse shells, obfuscation. And it *shows* you what it found instead of hiding it, because heuristics throw false positives and the call should be yours.

## Why not just ask Claude?

Because Claude's training data has a cutoff. Ask it what tools to use and you get last year's answer, delivered confidently — superseded tools, dead repos, and nothing that shipped this month.

Gold Digger fixes both ends: **what's new** comes from live sources, not memory. **What's established** gets verified with a real fetch before it's recommended — still exists, still maintained. If it can't verify, it tells you.

And the skill *is* the routine: same sources, same bar, same honesty, every single run — instead of hoping you write the perfect prompt every time.

## Install

The easy way:

```bash
npx skills add jaimeramiro-dev/gold-digger
```

Then install the two Python deps (the skill will remind you if you forget):

```bash
pip install -r ~/.claude/skills/gold-digger/requirements.txt
```

The manual way:

```bash
git clone https://github.com/jaimeramiro-dev/gold-digger.git ~/.claude/skills/gold-digger
cd ~/.claude/skills/gold-digger && pip install -r requirements.txt
```

Dependencies are deliberately tiny: PyYAML and feedparser. Everything else is Python stdlib.

## First run

It auto-detects your environment, then asks what you're actually building — the product, how it makes money, what eats your time. From that it derives the dimensions of your project (a game needs animation, UI, analytics; a SaaS needs billing, onboarding, email) and watches those too, not just your stack. That's the whole setup. Your profile lives in `~/.claude/gold-digger/profile.yaml`, outside the skill folder, so reinstalling never wipes it.

Optional but recommended — a free GitHub token bumps your rate limit from 60 to 5,000 requests/hour:

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

## How to talk to it

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
💡 KNOWN    <established tool you're missing — verified live, not from memory>
- DROP      <tool> — unused or superseded
~ Nothing worth your attention right now
```

## How the filter works

Cheap first, expensive only on survivors. Each user runs this on their own Claude, so the design keeps cost and time down.

```
  SCOUT             STAGE 1          STAGE 2           STAGE 2.5          SAFETY
  ─────             ───────          ───────           ─────────          ──────
  ~30 candidates    metadata only,   relevance +       the established    static scan
  from MCP regs,    no tool calls    liveness +        tool you're        on the final
  GitHub, HN,       ↓                switching cost    missing — from     1–3 only
  lab changelogs    ~30 → 8–10       ↓                 knowledge,         ↓
  (parallel)                         → 1–3             verified live      flags shown
```

The scripts do the mechanical work — fetching, parsing, scoring. Claude makes the judgment call. That split is deliberate: deterministic where it should be deterministic, and a real opinion where it counts.

## Sources

**Layer 1 — ecosystem-wide:** Official MCP Registry, Glama, GitHub (topics + your project's dimensions), Hacker News, Product Hunt, OSS Insight, Reddit. The MCP and connector registries are *the* channel for "X now connects to Claude."

**Layer 2 — per-tool, from your profile:** RSS feeds and GitHub releases for OpenAI, DeepMind, Anthropic, Meta AI, DeepSeek, and whatever's in your stack.

All free. No paid APIs. Each user runs on their own Claude with their own credentials — the creator's keys are never in the skill.

## Found gold?

Gold Digger saves you a week of digging, a star ⭐️ cost zero and helps us immensely. Fair trade.

## License

[MIT](LICENSE) — use it however you want.

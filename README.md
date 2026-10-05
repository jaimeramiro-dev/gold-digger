<p align="center">
  <img src="assets/logo.png" alt="Gold Digger" width="120">
</p>

<h1 align="center">Gold Digger</h1>

<p align="center">
  <img src="https://img.shields.io/github/stars/jaimeramiro-dev/gold-digger?style=flat&color=yellow">
  <img src="https://img.shields.io/github/last-commit/jaimeramiro-dev/gold-digger?style=flat">
  <img src="https://img.shields.io/github/license/jaimeramiro-dev/gold-digger?style=flat">
</p>

A thousand new tools, MCPs, skills, APIs and AI models drop every week. You bookmark a dozen, install three, use none — and the one that would actually change your project shipped last month and nobody told you. Gold Digger builds the best portfolio for *your* project from live sources, tells you what in your setup is dead weight, and stays quiet when nothing earns a place.

It's a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill. MIT, free to run. And yes, it's named Gold Digger because it's shamelessly only after the good stuff. No apologies.

[Install](#install) • [See it work](#see-it-work) • [Why it's not another feed](#why-its-not-another-feed) • [Why not just ask Claude?](#why-not-just-ask-claude)

---

## See it work

Ask for your portfolio. It reads your project and your real usage, maps what the project needs, and tells you in a few lines what you're missing and what's dead weight:

```
> Build my portfolio

  Your portfolio for Lars (operations AI for law firms), checked live today.

  What you're missing:
  - Legalize: Spain's legislation as versioned official text, with an official
    MCP. Today every legal search re-reads ~106k tokens of web pages.
  - VeriFactu: Lars issues invoices and it's mandatory from 2027-01-01.
    Nothing clears the bar yet — build it or integrate an API?

  What's surplus:
  - 19 of the 21 caveman skills: never used in this project.
  - Roblox Studio MCP: 0 calls in 60 days, in any project.

  The rest is well covered. Want me to install Legalize?
```

Short on purpose. Every number, source and safety verdict behind each line is saved and one question away ("why?", "show sources") — copied verbatim from live data, never made up.

The part I'm actually proud of: when there's nothing good, it says so. No filler pick to look busy.

```
> What's worth my attention?

  ~ Nothing worth your attention right now.

  Looked at 30 candidates across 6 sources. A few were close. None of
  them earned the swap.
```

## Why it's not another feed

Finding tools was never the problem. There are too many, and 99% of them aren't for you. Feeds, newsletters and "awesome-X" lists make it worse — more to read, not less.

- **It starts from your project, not the timeline.** It works out what your project needs end to end — not just code: assets, payments, distribution, the AI it leans on — and fills those needs. A game, a SaaS and a video channel get completely different portfolios.
- **It audits what you already have.** It reads your Claude Code history to see which MCPs and skills you actually call, and which dependencies you actually import. Unused, duplicated, or wrong-project tools get called out.
- **It knows noise when it sees it.** Clones of a skill with inflated install counts, re-publishers of someone else's MCP, a 2-week-old repo with 300K installs and 40 stars, awesome-lists, dead repos. The original and official wins; the copy gets named for what it is.
- **The numbers are real.** Installs, stars, downloads, dates — verbatim from data fetched in that run.
- **It scans before you install.** Skills come with the four-auditor security check from skills.sh; repos and MCP servers get a static red-flag scan. Flags are shown, not hidden — heuristics throw false positives and the call is yours.

## Why not just ask Claude?

Because the model's memory is stale by definition. Ask it what to use and you get last year's answer, delivered confidently — and it has never heard of the thing that launched last month.

So Gold Digger has one hard rule: **the model's memory is never a source.** Every candidate has to show up in live results during that run — skills.sh, the MCP registry, GitHub, npm, Hacker News, or a web search verified with a live check. The model decides *what to search for* and *judges what comes back*. It searches by capability ("text to speech api", "decision model"), not just brand names it already knows, so new tools it has never seen can still win.

And the skill *is* the routine: same sources, same bar, same honesty, every run.

## Install

```bash
npx skills add jaimeramiro-dev/gold-digger
pip install -r ~/.claude/skills/gold-digger/requirements.txt
```

Or manually:

```bash
git clone https://github.com/jaimeramiro-dev/gold-digger.git ~/.claude/skills/gold-digger
cd ~/.claude/skills/gold-digger && pip install -r requirements.txt
```

One dependency: PyYAML. Everything else is Python stdlib.

## First run

It inventories your project and your Claude setup — dependencies, config files, the services your env var *names* point to (never the values), every MCP server, plugin and skill, and how often you've actually used each one. Then it asks four plain questions: what you're making, how it makes money, what eats your time, and what you use outside the repo. From that it derives your project's needs and shows them to you. Your profile lives in `~/.claude/gold-digger/`, outside the skill folder, so reinstalling never wipes it.

GitHub limits are handled automatically if you have `GITHUB_TOKEN`, `GH_TOKEN`, or the `gh` CLI logged in.

## How to talk to it

| You say | It does |
| --- | --- |
| *"Build my portfolio"* / *"What am I missing?"* | Needs → audit what you have → live search → keep / add / swap / drop per need |
| *"Audit my setup"* / *"What can I drop?"* | Same run, focused on what's surplus |
| *"What's worth my attention?"* | Radar: this week's launches, judged against your portfolio — 1–3 moves or silence |
| *"Consider this: `<link>`"* | Saves a link to weigh on the next run (or now, if you ask) |
| *"That was a miss"* | Recalibrates — that topic gets weighted down |
| *"Think lateral about this"* | Speculative mode — non-obvious uses across your needs |

## How it works

```
  INVENTORY          NEEDS              LIVE SEARCH                 JUDGE              SAFETY
  ─────────          ─────              ───────────                 ─────              ──────
  deps, configs,     derived from       skills.sh · MCP registry    noise vs gold      skills.sh audits
  services, MCPs,    product, money,    GitHub · npm · HN           rubric: fit,       + static scan
  skills, plugins    pain points,       + web search for products,  alive, canonical,  on the picks only
  + real usage       what you have      services and AI models      credible, net win
                                        (every hit verified live)
```

The scripts do the mechanical work — fetching, grouping clones, pulling audits, mining usage. Claude makes the judgment call.

## Sources

**Portfolio search (keyword, no date limit):** [skills.sh](https://skills.sh) search + security audits (the API behind `npx skills find`), the Official MCP Registry, GitHub, npm, Hacker News, and web search for everything that isn't in a registry — verified with a live check before it can be recommended.

**Radar (what's new):** MCP Registry updates, GitHub (topics + your needs), Hacker News, release feeds for the AI labs and for whatever is in your stack.

All free. No paid APIs. Each user runs on their own Claude with their own credentials.

## Found gold?

Gold Digger saves you a week of digging, a star ⭐️ cost zero and helps us immensely. Fair trade.

## License

[MIT](LICENSE) — use it however you want.

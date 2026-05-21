# Gold Digger

Digs through the noise of new tools, skills, MCPs, and capabilities and surfaces only what's worth your attention — or tells you there's nothing this week. Scans for red flags before you install anything.

A Claude Code skill. MIT licensed. Free to run.

## The problem

There are thousands of new AI tools, MCP servers, and skills launching every week. Keeping up is a full-time job. Most "discovery" solutions make it worse — they're feeds, newsletters, and directories that add more noise.

## What makes this different

- **Silence is a feature.** If nothing clears the bar, the answer is "Nothing worth your attention right now." It will not invent recommendations to seem useful.
- **Primary sources, not blogspam.** Hits MCP registries, GitHub APIs, lab changelogs, and HN directly — where launches actually happen — instead of SEO articles written about them later.
- **Safety scan before install.** Statically analyzes any skill or MCP it recommends for red flags (credential access, reverse shells, obfuscation) before you install it.
- **Adapts to you.** Auto-detects your stack, asks about your other domains (marketing, design, gaming, whatever you do), and only surfaces what's relevant to your work.

## Install

### Option A: npx skills (recommended)

```bash
npx skills add jaimeramiro-dev/gold-digger
```

### Option B: Manual

```bash
git clone https://github.com/jaimeramiro-dev/gold-digger.git ~/.claude/skills/gold-digger
cd ~/.claude/skills/gold-digger && pip install -r requirements.txt
```

## Setup

On first run, Gold Digger auto-detects your environment and asks one short question about your domains. That's it.

Optional: set a free GitHub token for better coverage (5,000 requests/hour vs 60):

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

## Usage

Just talk to Claude naturally:

| What you say | What happens |
|---|---|
| "What's worth my attention?" | Scouts sources, filters, returns 1-3 moves or silence |
| "Consider this: \<link\>" | Captures a link for evaluation on your next review |
| "That was a miss" | Calibrates — the topic gets weighted down in future reviews |
| "Think lateral about this" | Speculative mode — looks for non-obvious cross-domain fits |

## Output format

Recommendations come as a diff on your setup:

```
+ ADD: <tool> — because <specific reason tied to your work>.
↑ USE: <capability you already have but aren't using>.
⇄ CONNECT: <MCP/connector> brings a manual workflow into Claude.
- DROP: <tool> — unused or superseded.
~ Nothing worth your attention right now.
```

## How the filter decides

1. **Scout** pulls from MCP registries, GitHub, Hacker News, lab changelogs, and more (~30 candidates).
2. **Stage 1** (cheap): Claude pre-filters on metadata only — keeps ~8-10.
3. **Stage 2** (deep): Fetches details, checks dedupe, weighs switching cost — keeps 1-3.
4. **Safety scan**: Only on the final 1-3, before showing them to you.
5. **Output**: The diff, or silence.

## Sources

Layer 1 (ecosystem-wide): Official MCP Registry, Glama, GitHub (topics: `mcp-server`, `agent-skills`), Hacker News, Product Hunt, OSS Insight, Reddit.

Layer 2 (per-tool, from your profile): RSS feeds and GitHub releases for OpenAI, DeepMind, Anthropic, Meta AI, DeepSeek, and whatever's in your stack.

All free. No paid APIs. Each user runs on their own Claude instance.

## License

MIT

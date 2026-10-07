# JagerLeagueBot
Since we're down 1 person, we use a bot (gusonthego) to fill in the gap. However, gusonthego only drafts the lowest possible ADP possible which means they barely score any points. To help them out, we compare gusonthego's opponent to the median score of all other teams that week (excluding gusonthego and the opponent). If the opponent scores under that median, gusonthego gets the opponent's score + 1 and wins. Otherwise gusonthego's score is left as is and it loses.

## Bot score

```
python JagerLeagueBotScoreCalculator.py --week 5
```

## Weekly recaps

Every Tuesday morning, GitHub Actions pulls the last completed week from Sleeper, has an AI model write an ESPN-style recap for each matchup, and posts it to a Discord channel: one overview message with the week's awards, then one message per matchup.

### Setup (repo Settings → Secrets and variables → Actions)

| Name | Kind | Value |
|---|---|---|
| `JAGER_LEAGUE_ID` | Variable | This season's Sleeper league ID (it changes every season; it's in the league URL) |
| `DISCORD_WEBHOOK_URL` | Secret | Discord channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy URL |
| `JAGER_BOT_ROSTER_ID` | Variable | Optional. GUSBOT's Sleeper roster ID (10 in the 2026 league) |

The writing uses [GitHub Models](https://docs.github.com/en/github-models) by default: free, rate-limited, and authenticated with the workflow's own token, so there's no key to add. Optional settings:

| Name | Kind | Value |
|---|---|---|
| `JAGER_MODEL` | Variable | GitHub Models model ID (default `openai/gpt-4.1`) |
| `JAGER_LLM` | Variable | Set to `claude` to use the Claude API instead |
| `ANTHROPIC_API_KEY` | Secret | Only needed with `JAGER_LLM=claude`; from console.anthropic.com |

Without `JAGER_BOT_ROSTER_ID`, the bot is found by its Sleeper name (`gusonthego`) or by its tiny potential points. Scores use the commissioner's override when Sleeper has one.

### Running it by hand

From the Actions tab, run **Weekly recap** with an optional week number. `dry_run` defaults to on and prints the recap to the job log without posting.

Locally:

```
pip install -r requirements.txt
python weekly_recap.py --week 5 --dry-run
python weekly_recap.py --fixture tests/fixtures/week.json --no-ai --dry-run   # no network or keys needed
```

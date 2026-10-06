# JagerLeagueBot
Since we're down 1 person, we use a bot (gusonthego) to fill in the gap. However, gusonthego only drafts the lowest possible ADP possible which means they barely score any points. To help them out, we compare gusonthego's opponent to the median score of all other teams that week (excluding gusonthego and the opponent). If the opponent scores under that median, gusonthego gets the opponent's score + 1 and wins. Otherwise gusonthego's score is left as is and it loses.

## Bot score

```
python JagerLeagueBotScoreCalculator.py --week 5
```

## Weekly recaps

Every Tuesday morning, GitHub Actions pulls the last completed week from Sleeper, has Claude write an ESPN-style recap for each matchup, and posts it to a Discord channel: one overview message with the week's awards, then one message per matchup.

### Setup (repo Settings → Secrets and variables → Actions)

| Name | Kind | Value |
|---|---|---|
| `JAGER_LEAGUE_ID` | Variable | This season's Sleeper league ID (it changes every season; it's in the league URL) |
| `ANTHROPIC_API_KEY` | Secret | Claude API key from console.anthropic.com |
| `DISCORD_WEBHOOK_URL` | Secret | Discord channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy URL |

The bot is found by its Sleeper name (`gusonthego`). To pin it exactly, add a `JAGER_BOT_ROSTER_ID` variable (roster 10 in the 2026 league). Scores use the commissioner's override when Sleeper has one.

### Running it by hand

From the Actions tab, run **Weekly recap** with an optional week number. `dry_run` defaults to on and prints the recap to the job log without posting.

Locally:

```
pip install -r requirements.txt
python weekly_recap.py --week 5 --dry-run
python weekly_recap.py --fixture tests/fixtures/week.json --no-ai --dry-run   # no network or keys needed
```

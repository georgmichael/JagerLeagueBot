# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

The Jager fantasy football league on Sleeper is one person short, so a bot team ("gusonthego" / GUSBOT) fills the empty slot. The bot drafts the lowest-ADP players and barely scores, so its real score is replaced with a substitute each week. `weekly_report.py` posts a weekly recap of the results to Discord.

## Running

```bash
pip install -r requirements.txt
python JagerLeagueBotScoreCalculator.py --week 4      # prints the GUSBOT result (prompts for a week without --week)
python weekly_report.py --dry-run                     # prints the weekly recap instead of posting it
```

Both scripts call the public Sleeper API (`https://api.sleeper.app/v1`) live. There are no tests and no lint config. Use `--dry-run` for `weekly_report.py` so nothing is posted to Discord.

## How it works

`JagerLeagueBotScoreCalculator.py` has the league logic. `week_results(league, week)` fetches the week's matchups, rosters and users, joins them (`roster_id` → `owner_id` → user), and works out the GUSBOT game:
- The bot is found by its Sleeper username (`BOT_USERNAME = "gusonthego"`), not by a 0 score, because it can score a few points.
- The league rule: GUSBOT wins when its opponent scores under the **median** of every team except the bot and its opponent. The opponent is left out on purpose (commit d206b37) to avoid ties. GUSBOT's score is then the opponent's score rounded up to the next whole point (`floor + 1`, so 117.32 → 118 and 117.00 → 118). Otherwise GUSBOT loses with its own real score. This matches what the commissioner enters in Sleeper by hand.
- Every score uses the commissioner's override (`custom_points` in Sleeper's matchup data) when there is one. When the commissioner has set GUSBOT's score, that score is used instead of the rule.
- It raises `ValueError` when the week has no scores yet or the bot has no matchup (off-season, playoffs).
- `LEAGUE_ID` is hard-coded and **changes every Sleeper season**. Find the new one with `GET /user/<user_id>/leagues/nfl/<season>` and look for "Jager League".

`weekly_report.py` imports from the calculator, sends a plain-text summary to an LLM to write the recap, and posts it to a Discord webhook. Notes:
- By default it reports on Sleeper's current week minus 1. Sleeper moves to the next week once Monday night's game ends.
- The LLM is any OpenAI-compatible chat completions API, set with `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL`. The default is the Gemini API free tier (`gemini-3.8-flash`, key from Google AI Studio). GitHub Models was retired on July 30, 2026, so don't use it.
- After the recap, it posts a funny manga of each matchup (GUSBOT's game included), drawn by Nano Banana (`IMAGE_MODEL`, default `gemini-nano-banana-2.1`) through the Gemini Interactions API with the same `LLM_API_KEY`. Image models have no free tier, so the key's project needs billing (about $0.03 per image). A manga that fails is skipped. All manga are drawn before anything is posted. `--no-manga` turns them off, and `--dry-run` saves them to `manga/`.
- If there's no key or the LLM call fails, it posts the plain summary. With `--no-fallback`, it exits with an error and posts nothing. The GUSBOT result line is always added by the code, not left to the model.

## CI

- `.github/workflows/ci.yml` runs `py_compile` on both scripts on push and PR. It only checks syntax.
- `.github/workflows/weekly-report.yml` runs Tuesdays at 1 a.m. Eastern year-round (two UTC cron entries, one for EDT and one for EST; the job skips the one that doesn't match) and can also be run by hand with an optional `week`. It passes `--no-fallback` and reruns the script every 15 minutes for up to about 5.5 hours until the LLM writes the recap, so the plain summary is never posted from CI. It needs the repo secrets `LLM_API_KEY` and `DISCORD_WEBHOOK_URL`. The repo variables `LLM_BASE_URL`, `LLM_MODEL` and `IMAGE_MODEL` are optional. A dry run uploads the manga as a `manga` workflow artifact.

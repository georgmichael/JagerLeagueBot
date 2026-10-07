"""Write the weekly Jager League recap with an LLM and post it to Discord.

Any OpenAI-compatible chat completions API works. The default is the Gemini API free tier.

Environment:
  LLM_API_KEY          Gemini API key from aistudio.google.com (without it, the plain summary is posted)
  LLM_BASE_URL         OpenAI-compatible base URL (default: Gemini's OpenAI-compatible endpoint)
  LLM_MODEL            model ID (default: gemini-3.8-flash)
  DISCORD_WEBHOOK_URL  Discord channel webhook (not needed with --dry-run)
"""
import argparse
import os
import sys
import time
from collections import defaultdict

import requests

from JagerLeagueBotScoreCalculator import BOT_USERNAME, LEAGUE_ID, current_nfl_week, result_line, week_results

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-3.8-flash"
DISCORD_LIMIT = 2000
# Seconds to wait before each retry when the model is overloaded or rate-limited
RETRY_DELAYS = [10, 30, 60]
RETRY_STATUSES = {429, 500, 502, 503, 504}

SYSTEM_PROMPT = """You write the weekly recap for the Jager League, a 10-team fantasy football league among friends.
One slot is filled by a bot, GUSBOT, whose real score doesn't count. Its official score is the median of the
other teams' scores, not counting its opponent. Write a short recap for Discord in the voice of a
SportsCenter highlights anchor, in the style of Scott Van Pelt and Chris "Boomer" Berman: dry, deadpan
sympathy for blowout losers and bad beats, over-the-top play-by-play energy for big scores, and playful
puns on team names. Keep it slightly comedic and good-natured: rib the losers, but don't be mean. Don't claim
to be either anchor or quote their catchphrases word for word.

Format: a headline, one or two lines per matchup, and the GUSBOT result. Use only the scores given and don't
invent player stats. Use Discord markdown and keep it under 1500 characters."""


def matchup_summary(results):
    """Plain-text summary of the week, used as the model's input and as the fallback post."""
    games = defaultdict(list)
    for team in results["teams"]:
        if team["owner"] != BOT_USERNAME and team["matchup_id"] is not None:
            games[team["matchup_id"]].append(team)

    lines = [f"**Jager League: Week {results['week']}**"]
    bot_opponent = results["opponent"]
    for teams in games.values():
        if bot_opponent in teams:
            continue
        a, b = sorted(teams, key=lambda team: team["points"], reverse=True)
        lines.append(f"{a['team_name']} ({a['owner']}) {a['points']:.2f} def. "
                     f"{b['team_name']} ({b['owner']}) {b['points']:.2f}")

    lines.append(f"GUSBOT game: GUSBOT {results['bot_score']:.2f} vs. "
                 f"{bot_opponent['team_name']} ({bot_opponent['owner']}) {bot_opponent['points']:.2f}. "
                 f"{result_line(results)}")
    return "\n".join(lines)


def write_recap(summary, api_key, base_url, model):
    for delay in RETRY_DELAYS + [None]:
        try:
            response = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": summary},
                    ],
                },
                timeout=60,
            )
        except (requests.ConnectionError, requests.Timeout) as error:
            if delay is None:
                raise
            print(f"Model request failed ({error}), retrying in {delay}s", file=sys.stderr)
        else:
            if response.status_code not in RETRY_STATUSES or delay is None:
                break
            print(f"Model returned {response.status_code}, retrying in {delay}s", file=sys.stderr)
        time.sleep(delay)
    if not response.ok:
        print(f"Model error response: {response.text[:500]}", file=sys.stderr)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def post_to_discord(webhook_url, content):
    if len(content) > DISCORD_LIMIT:
        content = content[:DISCORD_LIMIT - 1] + "…"
    response = requests.post(webhook_url, json={"content": content}, timeout=30)
    response.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", type=int, help="week to report on (default: the last completed week)")
    parser.add_argument("--dry-run", action="store_true", help="print the recap instead of posting it")
    args = parser.parse_args()

    # Sleeper moves to the next week once Monday night's game ends, so the last completed week is one behind.
    week = args.week or current_nfl_week() - 1
    if week < 1:
        print("No completed week to report on yet")
        return

    try:
        results = week_results(LEAGUE_ID, week)
    except ValueError as error:
        # Off-season, playoffs without GUSBOT, or a week with no scores
        print(f"Skipping report: {error}")
        return

    summary = matchup_summary(results)
    recap = summary
    api_key = os.environ.get("LLM_API_KEY")
    if api_key:
        try:
            recap = write_recap(summary, api_key,
                                os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL,
                                os.environ.get("LLM_MODEL") or DEFAULT_MODEL)
            # The GUSBOT result is the point of the report, so never rely on the model to state it.
            recap += f"\n\n🤖 {result_line(results)}"
        except (requests.RequestException, KeyError, IndexError) as error:
            print(f"Model call failed, posting the plain summary instead: {error}", file=sys.stderr)
    else:
        print("LLM_API_KEY not set, posting the plain summary", file=sys.stderr)

    if args.dry_run:
        print(recap)
        return

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        sys.exit("DISCORD_WEBHOOK_URL is not set")
    post_to_discord(webhook_url, recap)
    print(f"Posted week {week} recap to Discord")


if __name__ == "__main__":
    main()

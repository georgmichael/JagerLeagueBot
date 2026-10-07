"""Builds ESPN-style recaps for every matchup in a Sleeper week and posts them to Discord.

Usage:
  python weekly_recap.py                     # last completed week, posted to Discord
  python weekly_recap.py --week 5 --dry-run  # print instead of posting
  python weekly_recap.py --fixture tests/fixtures/week.json --no-ai --dry-run

Environment:
  JAGER_LEAGUE_ID      Sleeper league ID for the current season (it changes every season)
  JAGER_LLM            "github" (default, GitHub Models via GITHUB_TOKEN) or "claude" (ANTHROPIC_API_KEY)
  DISCORD_WEBHOOK_URL  Channel webhook (not needed with --dry-run)
"""

import argparse
import json
import os
import sys

from jagerbot import discord, sleeper, week as week_mod


def resolve_week(league_id, state):
    """The week to recap: the current Sleeper week if it has scores, else the one before."""
    current = int(state["week"])
    matchups = sleeper.matchups(league_id, current)
    bot_id = week_mod.find_bot_roster_id(sleeper.users(league_id), sleeper.rosters(league_id), matchups)
    return current if week_mod.week_has_scores(matchups, bot_id) else current - 1


def load_data(args):
    if args.fixture:
        with open(args.fixture) as f:
            data = json.load(f)
        if args.week:
            data["week"] = args.week
        return data, True

    league_id = os.environ.get("JAGER_LEAGUE_ID")
    if not league_id:
        sys.exit("Set JAGER_LEAGUE_ID to this season's Sleeper league ID.")
    state = sleeper.nfl_state()
    if not args.week and state.get("season_type") not in ("regular", "post"):
        print(f"No games to recap (Sleeper season_type is {state.get('season_type')!r}).")
        sys.exit(0)
    league = sleeper.league(league_id)
    if str(league.get("season")) != str(state.get("season")):
        sys.exit(
            f"League {league_id} is from the {league.get('season')} season but the NFL season is "
            f"{state.get('season')}. Sleeper issues a new league ID each season; update JAGER_LEAGUE_ID."
        )
    latest = resolve_week(league_id, state)
    week = args.week or latest
    if week < 1 or week > int(state["week"]):
        sys.exit(f"Week {week} hasn't been played yet.")
    return sleeper.fetch_week(league_id, week), week == latest


def placeholder_recap(facts):
    return {
        "headline": "Recap preview (AI writing skipped)",
        "intro": "This is a dry run without the Claude API. Scores and awards below are real.",
        "matchups": [
            {"matchup_id": m["matchup_id"], "headline": "", "recap": f"Margin: {m['margin']} points."}
            for m in facts["matchups"]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", type=int, help="Week to recap (default: last completed week)")
    parser.add_argument("--fixture", help="Read Sleeper data from a JSON file instead of the API")
    parser.add_argument("--dry-run", action="store_true", help="Print the Discord messages instead of posting")
    parser.add_argument("--no-ai", action="store_true", help="Skip the Claude API and use placeholder prose")
    parser.add_argument("--save-facts", help="Write the week facts given to the writer to this path")
    args = parser.parse_args()

    data, is_latest = load_data(args)
    facts = week_mod.build_week(data, include_records=is_latest)
    if not facts["matchups"]:
        sys.exit(f"No matchups found for week {facts['week']}.")
    if args.save_facts:
        with open(args.save_facts, "w") as f:
            json.dump(facts, f, indent=2)

    if args.no_ai:
        recap = placeholder_recap(facts)
    else:
        from jagerbot.writer import write_recap
        recap = write_recap(facts)

    messages = discord.build_messages(facts, recap)
    if args.dry_run:
        print(json.dumps(messages, indent=2))
        return

    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        sys.exit("Set DISCORD_WEBHOOK_URL, or pass --dry-run.")
    discord.post(webhook, messages)
    print(f"Posted week {facts['week']} recap ({len(facts['matchups'])} matchups).")


if __name__ == "__main__":
    main()

import argparse
import math
import statistics

import requests

SLEEPER_API = "https://api.sleeper.app/v1"

# Jager Sleeper League. The ID changes every season.
LEAGUE_ID = "1389329073896968194"
# Sleeper username of the bot that fills the empty slot
BOT_USERNAME = "gusonthego"


def get_json(path):
    response = requests.get(f"{SLEEPER_API}{path}", timeout=30)
    response.raise_for_status()
    return response.json()


def current_nfl_week():
    return int(get_json("/state/nfl")["week"])


def team_points(matchup):
    """A team's score for the week. A commissioner's score edit is stored in custom_points and replaces the raw score."""
    custom = matchup.get("custom_points")
    return float(custom if custom is not None else matchup["points"] or 0)


def week_results(league, week):
    """Return every team's score for the week plus the GUSBOT game result.

    GUSBOT wins when its opponent scores under the median of all teams except
    GUSBOT and the opponent (leaving the opponent out avoids ties). Its score is
    then the opponent's score rounded up to the next whole point. Otherwise it
    loses with its own real score. When the commissioner has already set
    GUSBOT's score in Sleeper, that score is used instead.
    """
    matchups = get_json(f"/league/{league}/matchups/{week}")
    rosters = get_json(f"/league/{league}/rosters")
    users = get_json(f"/league/{league}/users")

    users_by_id = {user["user_id"]: user for user in users}
    owner_by_roster = {roster["roster_id"]: roster["owner_id"] for roster in rosters}

    teams = []
    for matchup in matchups:
        user = users_by_id.get(owner_by_roster.get(matchup["roster_id"]), {})
        teams.append({
            "roster_id": matchup["roster_id"],
            "matchup_id": matchup["matchup_id"],
            "owner": user.get("display_name", "Unknown"),
            "team_name": (user.get("metadata") or {}).get("team_name") or user.get("display_name", "Unknown"),
            "points": team_points(matchup),
            "raw_points": float(matchup["points"] or 0),
        })

    if all(team["points"] == 0 for team in teams):
        raise ValueError(f"Week {week} has no scores yet")

    bot = next((team for team in teams if team["owner"] == BOT_USERNAME), None)
    if bot is None or bot["matchup_id"] is None:
        raise ValueError(f"{BOT_USERNAME} has no matchup in week {week}")

    opponent = next(team for team in teams
                    if team["matchup_id"] == bot["matchup_id"] and team is not bot)
    median = statistics.median(team["points"] for team in teams
                               if team is not bot and team is not opponent)
    if bot["points"] != bot["raw_points"]:
        bot_score = bot["points"]
    elif opponent["points"] < median:
        bot_score = math.floor(opponent["points"]) + 1
    else:
        bot_score = bot["raw_points"]

    return {
        "week": week,
        "teams": teams,
        "bot_score": bot_score,
        "median": median,
        "bot_actual_score": bot["raw_points"],
        "opponent": opponent,
        "bot_won": opponent["points"] < bot_score,
    }


def result_line(results):
    opponent = results["opponent"]
    if results["bot_won"]:
        return f"GUSBOT beat {opponent['owner']} with the score of {results['bot_score']:.2f} to {opponent['points']:.2f}"
    return f"{opponent['owner']} beat GUSBOT with a score of {opponent['points']:.2f} to {results['bot_score']:.2f}"


def main():
    parser = argparse.ArgumentParser(description="Calculate GUSBOT's score for a week")
    parser.add_argument("--week", type=int, help="NFL week (prompts if omitted)")
    args = parser.parse_args()

    fantasy_week = current_nfl_week()
    week = args.week
    if week is None:
        week = int(input("LMK which week you're interested in seeing data for homie : "))
    while week > fantasy_week:
        print("Sheeeesh I can't predict the future.... yet \n")
        week = int(input("Wanna try again and give me an actual week: "))

    print(result_line(week_results(LEAGUE_ID, week)))


if __name__ == "__main__":
    main()

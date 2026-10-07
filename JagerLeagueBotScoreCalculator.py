import argparse
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


def week_results(league, week):
    """Return every team's score for the week plus the GUSBOT game result.

    GUSBOT's score is the median of all teams except GUSBOT and its opponent
    (leaving the opponent out avoids ties).
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
            "points": float(matchup["points"] or 0),
        })

    if all(team["points"] == 0 for team in teams):
        raise ValueError(f"Week {week} has no scores yet")

    bot = next((team for team in teams if team["owner"] == BOT_USERNAME), None)
    if bot is None or bot["matchup_id"] is None:
        raise ValueError(f"{BOT_USERNAME} has no matchup in week {week}")

    opponent = next(team for team in teams
                    if team["matchup_id"] == bot["matchup_id"] and team is not bot)
    bot_score = statistics.median(team["points"] for team in teams
                                  if team is not bot and team is not opponent)

    return {
        "week": week,
        "teams": teams,
        "bot_score": bot_score,
        "bot_actual_score": bot["points"],
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

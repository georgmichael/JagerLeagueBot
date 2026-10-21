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
            # (player_id, points) for each starter. An empty slot has player_id "0".
            "starters": [(player_id, float(points or 0)) for player_id, points
                         in zip(matchup.get("starters") or [], matchup.get("starters_points") or [])
                         if player_id != "0"],
            # Points for every player on the roster, bench included
            "players_points": {player_id: float(points or 0)
                               for player_id, points in (matchup.get("players_points") or {}).items()},
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
        "bot": bot,
        "bot_score": bot_score,
        "median": median,
        "bot_actual_score": bot["raw_points"],
        "opponent": opponent,
        "bot_won": opponent["points"] < bot_score,
    }


def season_results(league, week):
    """week_results() for every week from 1 through the given week."""
    return [week_results(league, each_week) for each_week in range(1, week + 1)]


def standings(season):
    """Every team's record through the season so far (a list from season_results()), best first, with GUSBOT's
    games scored by the league rule.

    Worked out from each week's matchups rather than Sleeper's roster records, which can lag a day behind.
    Ranked by wins, then points for, like Sleeper. Each record's "results" lists "W", "L" or "T" for each week.
    """
    records = {}
    for results in season:
        games = {}
        for team in results["teams"]:
            points = results["bot_score"] if team is results["bot"] else team["points"]
            record = records.setdefault(team["roster_id"], {"roster_id": team["roster_id"], "wins": 0, "losses": 0,
                                                            "ties": 0, "points_for": 0.0, "results": []})
            # The latest week's name wins, so a renamed team shows its current name
            record.update(team_name=team["team_name"], owner=team["owner"])
            record["points_for"] += points
            games.setdefault(team["matchup_id"], []).append((record, points))
        for game in games.values():
            if len(game) != 2:
                continue
            (a, a_points), (b, b_points) = game
            if a_points == b_points:
                for record in (a, b):
                    record["ties"] += 1
                    record["results"].append("T")
            else:
                winner, loser = (a, b) if a_points > b_points else (b, a)
                winner["wins"] += 1
                winner["results"].append("W")
                loser["losses"] += 1
                loser["results"].append("L")
    return sorted(records.values(), key=lambda record: (record["wins"] + record["ties"] / 2, record["points_for"]),
                  reverse=True)


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

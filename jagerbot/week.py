"""Turns raw Sleeper responses for one week into the facts a recap is written from."""

import os
import statistics

# The bot fills the empty league slot and never scores. Matched against the
# Sleeper display name or team name, case-insensitively.
BOT_NAME = os.environ.get("JAGER_BOT_NAME", "gusonthego")
BOT_LABEL = "GUSBOT"

SLOT_ELIGIBILITY = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "DL": {"DL"},
    "LB": {"LB"},
    "DB": {"DB"},
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "IDP_FLEX": {"DL", "LB", "DB"},
}


def _points(value):
    return round(float(value or 0), 2)


def player_info(players, player_id):
    p = players.get(player_id) or {}
    name = " ".join(filter(None, [p.get("first_name"), p.get("last_name")])) or player_id
    return {
        "name": name,
        "position": p.get("position") or "?",
        "nfl_team": p.get("team") or "FA",
        "fantasy_positions": p.get("fantasy_positions") or [p.get("position")],
    }


def optimal_points(roster_positions, players_points, players):
    """Best possible starting lineup score. Fills the most restrictive slots first."""
    slots = [s for s in roster_positions if s in SLOT_ELIGIBILITY]
    slots.sort(key=lambda s: len(SLOT_ELIGIBILITY[s]))
    available = sorted(players_points.items(), key=lambda kv: kv[1] or 0, reverse=True)
    used = set()
    total = 0.0
    for slot in slots:
        for player_id, pts in available:
            if player_id in used:
                continue
            if SLOT_ELIGIBILITY[slot] & set(player_info(players, player_id)["fantasy_positions"]):
                used.add(player_id)
                total += pts or 0
                break
    return round(total, 2)


def find_bot_roster_id(users, rosters, matchups):
    names = {
        u["user_id"]: {(u.get("display_name") or "").lower(), ((u.get("metadata") or {}).get("team_name") or "").lower()}
        for u in users
    }
    for roster in rosters:
        if BOT_NAME.lower() in names.get(roster.get("owner_id"), set()):
            return roster["roster_id"]
    # Fallback (the original heuristic): the only team that scored zero in a played week.
    zero = [m["roster_id"] for m in matchups if _points(m.get("points")) == 0]
    played = any(_points(m.get("points")) > 0 for m in matchups)
    if played and len(zero) == 1:
        return zero[0]
    return None


def league_median(matchups, bot_roster_id):
    """Median of every real team's score, excluding the bot and the bot's opponent."""
    bot = next((m for m in matchups if m["roster_id"] == bot_roster_id), None)
    if bot is None:
        return None, None
    opponent = next(
        (m for m in matchups if m.get("matchup_id") == bot.get("matchup_id") and m["roster_id"] != bot_roster_id),
        None,
    )
    excluded = {bot_roster_id, opponent["roster_id"] if opponent else None}
    points = [_points(m.get("points")) for m in matchups if m["roster_id"] not in excluded]
    return round(statistics.median(points), 2), opponent


def bot_score(matchups, bot_roster_id):
    """The bot's score. If its opponent scores under the median, the bot wins by
    exactly 1 point (opponent + 1). Otherwise it keeps its own Sleeper score and loses."""
    median, opponent = league_median(matchups, bot_roster_id)
    if median is None or opponent is None:
        return median, opponent
    opponent_points = _points(opponent.get("points"))
    if opponent_points < median:
        return round(opponent_points + 1, 2), opponent
    bot = next(m for m in matchups if m["roster_id"] == bot_roster_id)
    return _points(bot.get("points")), opponent


def week_has_scores(matchups, bot_roster_id=None):
    return any(_points(m.get("points")) > 0 for m in matchups if m["roster_id"] != bot_roster_id)


def build_week(data, include_records=False):
    league = data["league"]
    players = data["players"]
    users_by_id = {u["user_id"]: u for u in data["users"]}
    rosters_by_id = {r["roster_id"]: r for r in data["rosters"]}
    matchups = data["matchups"]
    roster_positions = league.get("roster_positions", [])

    bot_roster_id = find_bot_roster_id(data["users"], data["rosters"], matchups)
    median, _ = league_median(matchups, bot_roster_id) if bot_roster_id is not None else (None, None)
    gus_points, _ = bot_score(matchups, bot_roster_id) if bot_roster_id is not None else (None, None)

    def team(m):
        roster = rosters_by_id.get(m["roster_id"], {})
        user = users_by_id.get(roster.get("owner_id"), {})
        is_bot = m["roster_id"] == bot_roster_id
        manager = user.get("display_name") or f"Roster {m['roster_id']}"
        entry = {
            "roster_id": m["roster_id"],
            "team_name": BOT_LABEL if is_bot else ((user.get("metadata") or {}).get("team_name") or manager),
            "manager": BOT_LABEL if is_bot else manager,
            "is_bot": is_bot,
        }
        if include_records:
            s = roster.get("settings", {})
            entry["season_record"] = f"{s.get('wins', 0)}-{s.get('losses', 0)}" + (f"-{s['ties']}" if s.get("ties") else "")
        if is_bot:
            entry["points"] = gus_points
            entry["note"] = (
                "The bot does not play. If its opponent scores under the league median "
                "(excluding the bot and its opponent), the bot is given the opponent's score + 1 "
                "and wins; otherwise its score is not adjusted and it loses."
            )
            return entry

        players_points = {pid: _points(p) for pid, p in (m.get("players_points") or {}).items()}
        starters = [pid for pid in (m.get("starters") or []) if pid and pid != "0"]
        starter_ids = set(starters)
        entry["points"] = _points(m.get("points"))
        entry["starters"] = [
            {**{k: v for k, v in player_info(players, pid).items() if k != "fantasy_positions"}, "points": players_points.get(pid, 0.0)}
            for pid in starters
        ]
        bench = [
            {**{k: v for k, v in player_info(players, pid).items() if k != "fantasy_positions"}, "points": pts}
            for pid, pts in players_points.items()
            if pid not in starter_ids
        ]
        bench.sort(key=lambda p: p["points"], reverse=True)
        entry["top_bench"] = bench[:3]
        best = optimal_points(roster_positions, players_points, players)
        entry["optimal_points"] = best
        entry["points_left_on_bench"] = round(max(best - entry["points"], 0), 2)
        return entry

    games = {}
    for m in matchups:
        if m.get("matchup_id") is None:
            continue
        games.setdefault(m["matchup_id"], []).append(m)

    results = []
    for matchup_id in sorted(games):
        pair = games[matchup_id]
        if len(pair) != 2:
            continue
        a, b = sorted((team(m) for m in pair), key=lambda t: t["points"], reverse=True)
        results.append({
            "matchup_id": matchup_id,
            "winner": a,
            "loser": b,
            "tie": a["points"] == b["points"],
            "margin": round(a["points"] - b["points"], 2),
            "is_bot_game": a["is_bot"] or b["is_bot"],
        })

    return {
        "league_name": league.get("name", "Jager League"),
        "season": league.get("season"),
        "week": data["week"],
        "league_median": median,
        "matchups": results,
        "awards": awards(results),
    }


def awards(results):
    if not results:
        return {}
    real_teams = [t for r in results for t in (r["winner"], r["loser"]) if not t["is_bot"]]
    real_games = [r for r in results if not r["is_bot_game"]] or results
    starters = [(p, t["team_name"]) for t in real_teams for p in t.get("starters", [])]
    top_player = max(starters, key=lambda x: x[0]["points"], default=None)
    high = max(real_teams, key=lambda t: t["points"])
    low = min(real_teams, key=lambda t: t["points"])
    bench = max(real_teams, key=lambda t: t.get("points_left_on_bench", 0))
    closest = min(real_games, key=lambda r: r["margin"])
    blowout = max(real_games, key=lambda r: r["margin"])

    def game(r):
        return f"{r['winner']['team_name']} {r['winner']['points']} - {r['loser']['team_name']} {r['loser']['points']}"

    result = {
        "high_score": f"{high['team_name']} ({high['points']})",
        "low_score": f"{low['team_name']} ({low['points']})",
        "closest_game": f"{game(closest)} (margin {closest['margin']})",
        "biggest_blowout": f"{game(blowout)} (margin {blowout['margin']})",
        "most_points_left_on_bench": f"{bench['team_name']} ({bench.get('points_left_on_bench', 0)})",
    }
    if top_player:
        p, owner = top_player
        result["top_player"] = f"{p['name']} ({p['position']}, {p['nfl_team']}) - {p['points']} for {owner}"
    return result

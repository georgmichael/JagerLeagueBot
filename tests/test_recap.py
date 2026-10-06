import json
import os
from types import SimpleNamespace

import pytest

from jagerbot import discord, week, writer

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "week.json")


@pytest.fixture
def data():
    with open(FIXTURE) as f:
        return json.load(f)


def players(*specs):
    return {pid: {"first_name": pid, "last_name": "", "position": pos, "fantasy_positions": [pos]} for pid, pos in specs}


def test_bot_found_by_name(data):
    assert week.find_bot_roster_id(data["users"], data["rosters"], data["matchups"]) == 10


def test_bot_falls_back_to_only_zero_score():
    users = [{"user_id": "a", "display_name": "someone"}, {"user_id": "b", "display_name": "renamed"}]
    rosters = [{"roster_id": 1, "owner_id": "a"}, {"roster_id": 2, "owner_id": "b"}]
    matchups = [{"roster_id": 1, "points": 99.1}, {"roster_id": 2, "points": 0}]
    assert week.find_bot_roster_id(users, rosters, matchups) == 2


def test_bot_not_guessed_before_games_are_played():
    users = [{"user_id": "a", "display_name": "x"}, {"user_id": "b", "display_name": "y"}]
    rosters = [{"roster_id": 1, "owner_id": "a"}, {"roster_id": 2, "owner_id": "b"}]
    matchups = [{"roster_id": 1, "points": 0}, {"roster_id": 2, "points": 0}]
    assert week.find_bot_roster_id(users, rosters, matchups) is None


def test_bot_score_is_median_excluding_bot_and_opponent():
    matchups = [
        {"roster_id": 1, "matchup_id": 1, "points": 0},
        {"roster_id": 2, "matchup_id": 1, "points": 200},  # opponent, excluded
        {"roster_id": 3, "matchup_id": 2, "points": 100},
        {"roster_id": 4, "matchup_id": 2, "points": 110},
        {"roster_id": 5, "matchup_id": 3, "points": 90},
    ]
    score, opponent = week.bot_score(matchups, 1)
    assert score == 100
    assert opponent["roster_id"] == 2


def test_optimal_points_uses_flex_for_best_leftover():
    p = players(("qb", "QB"), ("rb1", "RB"), ("rb2", "RB"), ("wr1", "WR"), ("te1", "TE"), ("te2", "TE"))
    points = {"qb": 20, "rb1": 10, "rb2": 3, "wr1": 15, "te1": 8, "te2": 12}
    # QB 20 + RB 10 + WR 15 + TE 12, FLEX takes te1 (8) over rb2 (3)
    assert week.optimal_points(["QB", "RB", "WR", "TE", "FLEX", "BN"], points, p) == 65


def test_build_week_from_fixture(data):
    facts = week.build_week(data, include_records=True)
    assert facts["week"] == 5
    assert len(facts["matchups"]) == 5
    bot_game = [m for m in facts["matchups"] if m["is_bot_game"]]
    assert len(bot_game) == 1
    bot = next(t for t in (bot_game[0]["winner"], bot_game[0]["loser"]) if t["is_bot"])
    assert bot["points"] == facts["bot_median_score"]
    for m in facts["matchups"]:
        assert m["winner"]["points"] >= m["loser"]["points"]
        for t in (m["winner"], m["loser"]):
            if not t["is_bot"]:
                assert t["optimal_points"] >= t["points"]
                assert "season_record" in t


def test_records_left_out_for_past_weeks(data):
    facts = week.build_week(data, include_records=False)
    assert all("season_record" not in m["winner"] for m in facts["matchups"])


def test_discord_titles_use_sleeper_scores(data):
    facts = week.build_week(data)
    recap = {
        "headline": "H",
        "intro": "I",
        "matchups": [{"matchup_id": m["matchup_id"], "headline": "x", "recap": "y"} for m in facts["matchups"]],
    }
    messages = discord.build_messages(facts, recap)
    assert len(messages) == 1 + len(facts["matchups"])
    first = facts["matchups"][0]
    assert messages[1]["embeds"][0]["title"].startswith(f"{first['winner']['team_name']} {first['winner']['points']:.2f}")
    for msg in messages:
        assert len(msg["embeds"][0]["description"]) <= discord.EMBED_DESCRIPTION_LIMIT


class FakeClient:
    def __init__(self, response):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self._response = response

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_writer_parses_json(data):
    facts = week.build_week(data)
    body = {"headline": "h", "intro": "i", "matchups": []}
    client = FakeClient(SimpleNamespace(
        stop_reason="end_turn", stop_details=None,
        content=[SimpleNamespace(type="text", text=json.dumps(body))],
    ))
    assert writer.write_recap(facts, client=client) == body
    call = client.calls[0]
    assert call["model"] == writer.MODEL
    assert call["output_config"]["format"]["type"] == "json_schema"


def test_writer_raises_on_refusal(data):
    facts = week.build_week(data)
    client = FakeClient(SimpleNamespace(stop_reason="refusal", stop_details={"category": None}, content=[]))
    with pytest.raises(writer.RecapRefused):
        writer.write_recap(facts, client=client)

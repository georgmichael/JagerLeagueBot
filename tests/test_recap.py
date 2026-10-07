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


def roster(rid, ppts, ppts_decimal=0):
    return {"roster_id": rid, "owner_id": f"o{rid}", "settings": {"ppts": ppts, "ppts_decimal": ppts_decimal}}


def test_bot_falls_back_to_tiny_potential_points():
    # Real 2026 numbers: the bot's best possible lineup over 4 weeks was 10.60
    # even though the commissioner had raised its points for to 212.
    rosters = [roster(1, 462, 68), roster(2, 488, 94), roster(10, 10, 60)]
    assert week.find_bot_roster_id([], rosters, []) == 10


def test_bot_not_guessed_before_games_are_played():
    assert week.find_bot_roster_id([], [roster(1, 0), roster(2, 0)], []) is None


def test_bot_roster_id_override(monkeypatch):
    monkeypatch.setattr(week, "BOT_ROSTER_ID", "7")
    assert week.find_bot_roster_id([], [], []) == 7


def test_commissioner_override_is_used():
    assert week.team_points({"points": 3.2, "custom_points": 141.5}) == 141.5
    assert week.team_points({"points": 3.2, "custom_points": None}) == 3.2


def bot_week(opponent_points):
    return [
        {"roster_id": 1, "matchup_id": 1, "points": 2.4},
        {"roster_id": 2, "matchup_id": 1, "points": opponent_points},  # excluded from the median
        {"roster_id": 3, "matchup_id": 2, "points": 100},
        {"roster_id": 4, "matchup_id": 2, "points": 110},
        {"roster_id": 5, "matchup_id": 3, "points": 90},
    ]


def test_median_excludes_bot_and_opponent():
    median, opponent = week.league_median(bot_week(200), 1)
    assert median == 100
    assert opponent["roster_id"] == 2


def test_bot_keeps_own_score_when_opponent_beats_median():
    assert week.bot_score(bot_week(200), 1)[0] == 2.4


def test_bot_keeps_own_score_when_opponent_ties_median():
    assert week.bot_score(bot_week(100), 1)[0] == 2.4


def test_median_uses_commissioner_overrides():
    matchups = bot_week(200)
    matchups[2]["custom_points"] = 130  # roster 3: 100 -> 130
    assert week.league_median(matchups, 1)[0] == 110


def test_bot_wins_by_one_when_opponent_is_under_median():
    assert week.bot_score(bot_week(85.42), 1)[0] == 86.42


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
    assert bot["points"] == week.bot_score(data["matchups"], 10)[0]
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


def test_claude_writer_parses_json(data):
    facts = week.build_week(data)
    body = {"headline": "h", "intro": "i", "matchups": []}
    client = FakeClient(SimpleNamespace(
        stop_reason="end_turn", stop_details=None,
        content=[SimpleNamespace(type="text", text=json.dumps(body))],
    ))
    assert writer.write_recap(facts, provider="claude", client=client) == body
    call = client.calls[0]
    assert call["model"] == writer.CLAUDE_MODEL
    assert call["output_config"]["format"]["type"] == "json_schema"


def test_claude_writer_raises_on_refusal(data):
    facts = week.build_week(data)
    client = FakeClient(SimpleNamespace(stop_reason="refusal", stop_details={"category": None}, content=[]))
    with pytest.raises(writer.RecapRefused):
        writer.write_recap(facts, provider="claude", client=client)


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


def chat_reply(obj, finish_reason="stop"):
    return FakeResponse(200, {"choices": [{"finish_reason": finish_reason, "message": {"content": json.dumps(obj)}}]})


def test_github_models_one_request_per_matchup_plus_intro(data, monkeypatch):
    facts = week.build_week(data)
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        if "this one matchup" in json["messages"][1]["content"]:
            return chat_reply({"headline": "H", "recap": f"recap {len(calls)}"})
        return chat_reply({"headline": "Week headline", "intro": "Intro."})

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(writer.requests, "post", fake_post)
    recap = writer.write_recap(facts, provider="github")
    assert len(calls) == len(facts["matchups"]) + 1
    assert all(c["model"] == writer.GITHUB_MODEL for c in calls)
    assert recap["headline"] == "Week headline"
    assert [m["matchup_id"] for m in recap["matchups"]] == [m["matchup_id"] for m in facts["matchups"]]


def test_github_models_skips_a_failed_matchup(data, monkeypatch):
    facts = week.build_week(data)
    state = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        state["n"] += 1
        if state["n"] == 1:
            return FakeResponse(400, {"error": "content filtered"})
        if "this one matchup" in json["messages"][1]["content"]:
            return chat_reply({"headline": "H", "recap": "r"})
        return chat_reply({"headline": "W", "intro": "I"})

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(writer.requests, "post", fake_post)
    recap = writer.write_recap(facts, provider="github")
    assert len(recap["matchups"]) == len(facts["matchups"]) - 1
    # The skipped game still gets a Discord message, just without prose.
    assert len(discord.build_messages(facts, recap)) == 1 + len(facts["matchups"])


def test_github_models_needs_token(data, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        writer.write_recap(week.build_week(data), provider="github")

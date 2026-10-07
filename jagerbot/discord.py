"""Formats a recap as Discord embeds and posts it through a channel webhook."""

import time

import requests

COLOR = 0xCC0000
EMBED_DESCRIPTION_LIMIT = 4096


def _truncate(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_messages(week_facts, recap):
    """One overview message, then one message per matchup."""
    prose = {m["matchup_id"]: m for m in recap.get("matchups", [])}
    awards = week_facts.get("awards", {})
    award_labels = {
        "high_score": "High score",
        "low_score": "Low score",
        "top_player": "Top player",
        "closest_game": "Closest game",
        "biggest_blowout": "Biggest blowout",
        "most_points_left_on_bench": "Most points left on bench",
    }
    overview = {
        "title": _truncate(f"Week {week_facts['week']}: {recap['headline']}", 256),
        "description": _truncate(recap["intro"] or "\u200b", EMBED_DESCRIPTION_LIMIT),
        "color": COLOR,
        "fields": [
            {"name": label, "value": _truncate(awards[key], 1024), "inline": False}
            for key, label in award_labels.items()
            if awards.get(key)
        ],
    }
    messages = [{"embeds": [overview]}]

    for game in week_facts["matchups"]:
        w, l = game["winner"], game["loser"]
        verb = "tie" if game["tie"] else "def."
        written = prose.get(game["matchup_id"], {})
        # Scores in the title come from Sleeper, not from the model.
        scoreline = f"{w['team_name']} {w['points']:.2f} {verb} {l['team_name']} {l['points']:.2f}"
        description = ""
        if written.get("headline"):
            description += f"**{written['headline']}**\n\n"
        description += written.get("recap", "_No recap was written for this game._")
        messages.append({"embeds": [{
            "title": _truncate(scoreline, 256),
            "description": _truncate(description, EMBED_DESCRIPTION_LIMIT),
            "color": COLOR,
        }]})
    return messages


def post(webhook_url, messages, username="JagerLeagueBot"):
    for payload in messages:
        payload = {"username": username, **payload}
        for _ in range(5):
            response = requests.post(webhook_url, json=payload, timeout=30)
            if response.status_code == 429:
                time.sleep(float(response.json().get("retry_after", 1)))
                continue
            response.raise_for_status()
            break
        else:
            raise RuntimeError("Discord kept rate limiting the webhook")
        time.sleep(1)  # webhooks allow ~5 requests per 2 seconds

"""Writes ESPN-style recap prose from week facts using the Claude API."""

import json

import anthropic

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You write weekly fantasy football recaps for a private league of friends, in the voice of an ESPN game recap: a punchy headline, then a few tight paragraphs that tell the story of the game.

Ground rules:
- Use only the facts in the provided JSON. Do not invent stats, injuries, trades, quotes, or real-world NFL storylines. If a number is not in the data, do not state one.
- Refer to teams by team_name, and to managers by manager name when it reads naturally.
- Name the players who decided the game, using their points from the data. Mention points left on the bench when it would have changed the result or is notably large.
- Light trash talk is welcome; keep it good-natured.
- In the bot game, GUSBOT does not have a lineup. If its opponent scores under the league median, GUSBOT is given the opponent's score + 1 and wins; otherwise GUSBOT's score is not adjusted (usually 0) and it loses. A 1-point GUSBOT win is the rule, not a close game: never describe it as a nail-biter. Play the rule up with humour, but get it right.
- Each matchup recap should be 120 to 200 words. The intro should be 2 to 3 sentences setting up the week.
- Plain text only, no markdown headings. Bold (**like this**) is fine for player names."""

RECAP_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "intro": {"type": "string"},
        "matchups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "matchup_id": {"type": "integer"},
                    "headline": {"type": "string"},
                    "recap": {"type": "string"},
                },
                "required": ["matchup_id", "headline", "recap"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "intro", "matchups"],
    "additionalProperties": False,
}


class RecapRefused(Exception):
    pass


def write_recap(week_facts, client=None):
    client = client or anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": RECAP_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{
            "role": "user",
            "content": f"Write the recap for week {week_facts['week']}. Facts:\n\n{json.dumps(week_facts, indent=2)}",
        }],
    )
    if response.stop_reason == "refusal":
        raise RecapRefused(str(response.stop_details))
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Recap was cut off by max_tokens")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)

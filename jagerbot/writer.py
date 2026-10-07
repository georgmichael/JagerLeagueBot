"""Writes ESPN-style recap prose from week facts with an LLM.

Two providers, chosen with JAGER_LLM:
  github  GitHub Models (default). Free and rate-limited; in Actions it uses the
          workflow's GITHUB_TOKEN with the `models: read` permission. Requests are
          small (one per matchup) to stay under the free tier's per-request limits.
  claude  The Claude API. Needs ANTHROPIC_API_KEY. One request for the whole week.
"""

import json
import os
import sys
import time

import requests

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_MODEL = os.environ.get("JAGER_MODEL") or "openai/gpt-4.1"
CLAUDE_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You write weekly fantasy football recaps for a private league of friends, in the voice of an ESPN game recap: a punchy headline, then a few tight paragraphs that tell the story of the game.

Ground rules:
- Use only the facts in the provided JSON. Do not invent stats, injuries, trades, quotes, or real-world NFL storylines. If a number is not in the data, do not state one.
- Refer to teams by team_name, and to managers by manager name when it reads naturally.
- Name the players who decided the game, using their points from the data. Mention points left on the bench when it would have changed the result or is notably large.
- Light trash talk is welcome; keep it good-natured.
- In the bot game, GUSBOT does not have a lineup. If its opponent scores under the league median, GUSBOT is given the opponent's score + 1 and wins; otherwise GUSBOT keeps the handful of points its own lowest-ADP players scored and loses. A 1-point GUSBOT win is the rule, not a close game: never describe it as a nail-biter. Play the rule up with humour, but get it right.
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


def write_recap(week_facts, provider=None, client=None):
    provider = provider or os.environ.get("JAGER_LLM") or "github"
    if provider == "github":
        return _write_with_github_models(week_facts)
    if provider == "claude":
        return _write_with_claude(week_facts, client)
    raise ValueError(f"Unknown JAGER_LLM provider {provider!r} (use 'github' or 'claude')")


# --- GitHub Models -----------------------------------------------------------

def _github_chat(user_content, max_tokens=1200):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Set GITHUB_TOKEN (in Actions, grant the workflow `models: read`).")
    body = {
        "model": GITHUB_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        "temperature": 0.8,
    }
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    for _ in range(3):
        response = requests.post(GITHUB_MODELS_URL, json=body, headers=headers, timeout=120)
        if response.status_code == 429:
            time.sleep(min(float(response.headers.get("retry-after", 30)), 120))
            continue
        if response.status_code >= 400:
            raise RuntimeError(f"GitHub Models returned {response.status_code}: {response.text[:500]}")
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") == "length":
            raise RuntimeError("Response was cut off by max_tokens")
        return json.loads(choice["message"]["content"])
    raise RuntimeError("GitHub Models kept rate limiting the request")


def _write_with_github_models(week_facts):
    context = {
        "league_name": week_facts.get("league_name"),
        "week": week_facts["week"],
        "league_median": week_facts.get("league_median"),
    }
    matchups = []
    for game in week_facts["matchups"]:
        prompt = (
            "Write the recap for this one matchup. Reply with a JSON object with keys "
            '"headline" (string) and "recap" (string).\n\n'
            f"Week context:\n{json.dumps(context)}\n\nMatchup facts:\n{json.dumps(game)}"
        )
        try:
            written = _github_chat(prompt)
            matchups.append({
                "matchup_id": game["matchup_id"],
                "headline": str(written.get("headline", "")),
                "recap": str(written["recap"]),
            })
        except Exception as e:  # one bad game shouldn't sink the whole week
            print(f"Matchup {game['matchup_id']}: no recap written ({e})", file=sys.stderr)

    if not matchups:
        raise RuntimeError("No matchup recaps could be written")

    scoreboard = [
        f"{g['winner']['team_name']} {g['winner']['points']} - {g['loser']['team_name']} {g['loser']['points']}"
        for g in week_facts["matchups"]
    ]
    prompt = (
        "Write the headline and intro for this week's league-wide recap. Reply with a JSON object "
        'with keys "headline" (string) and "intro" (string).\n\n'
        f"Week context:\n{json.dumps(context)}\n\nScores:\n{json.dumps(scoreboard)}\n\n"
        f"Awards:\n{json.dumps(week_facts.get('awards', {}))}"
    )
    try:
        overview = _github_chat(prompt, max_tokens=400)
        headline, intro = str(overview["headline"]), str(overview["intro"])
    except Exception as e:
        print(f"Intro: not written ({e})", file=sys.stderr)
        headline, intro = f"Week {week_facts['week']} in the books", ""
    return {"headline": headline, "intro": intro, "matchups": matchups}


# --- Claude ------------------------------------------------------------------

def _write_with_claude(week_facts, client=None):
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
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

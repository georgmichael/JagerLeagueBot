"""Write the weekly Jager League recap with an LLM and post it to Discord, each matchup's recap followed by its manga,
then the league standings.

Any OpenAI-compatible chat completions API works for the recap. The default is the Gemini API.
The manga are drawn by Nano Banana through the Gemini API, which needs a key from a project with billing.

Environment:
  LLM_API_KEY          Gemini API key from aistudio.google.com (without it, the plain summary is posted)
  LLM_BASE_URL         OpenAI-compatible base URL (default: Gemini's OpenAI-compatible endpoint)
  LLM_MODEL            model ID (default: gemini-3.8-flash)
  IMAGE_MODEL          Nano Banana model ID (default: gemini-nano-banana-2.1)
  DISCORD_WEBHOOK_URL  Discord channel webhook (not needed with --dry-run)
"""
import argparse
import base64
import json
import os
import pathlib
import sys
import time
from collections import defaultdict

import requests

from JagerLeagueBotScoreCalculator import (BOT_USERNAME, LEAGUE_ID, current_nfl_week, get_json, result_line, standings,
                                           week_results)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-3.8-flash"
GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_IMAGE_MODEL = "gemini-nano-banana-2.1"
DISCORD_LIMIT = 2000
# Seconds to wait before each retry when the model is overloaded or rate-limited
RETRY_DELAYS = [10, 30, 60]
RETRY_STATUSES = {429, 500, 502, 503, 504}

SYSTEM_PROMPT = """You write the weekly recap for the Jager League, a 10-team fantasy football league among friends.
One slot is filled by a bot, GUSBOT, that barely scores. By league rule, GUSBOT wins when its opponent scores under
the median of the other teams (not counting GUSBOT and its opponent), and its score is set to the opponent's score
rounded up to the next whole point, so a narrow GUSBOT win is the rule at work, not a close game. Otherwise GUSBOT
loses with its own tiny real score, because its opponent beat the median. Write a short recap for Discord in the voice of a
SportsCenter highlights anchor, in the style of Scott Van Pelt and Chris "Boomer" Berman: dry, deadpan
sympathy for blowout losers and bad beats, over-the-top play-by-play energy for big scores, and playful
puns on team names. Keep it slightly comedic and good-natured: rib the losers, but don't be mean. Don't claim
to be either anchor or quote their catchphrases word for word.

The matchups are numbered. Reply with only a JSON object: {"headline": "...", "matchups": ["...", ...]}, where
"matchups" has one recap per numbered matchup, in the same order. Each recap is one to three sentences and under
400 characters, and the GUSBOT recap covers the GUSBOT result. Where each team's best and worst starter are given,
work them in: hype the hero who carried the team and roast the dud who sank it (a starter with 0.00 may have been
inactive, so ribbing the manager for starting them works too). Use only the scores and player points
given and don't invent other stats. Use Discord markdown in the text."""

MANGA_PROMPT = """A funny four-panel manga (2x2 grid, black and white with screentone shading, read left to right) about
a week-{week} fantasy football matchup in the Jager League, a league among friends.

{winner} ({winner_points:.2f} points) beat {loser} ({loser_points:.2f} points).

Turn each team into an over-the-top shonen manga character inspired by its team name. Build up to the result with
dramatic speed lines, sweat drops and reaction faces, and end with a comedic final panel where the winner gloats
and the loser despairs. Show the final score exactly as given on a scoreboard in the last panel. Keep any speech
bubbles short and in English, spell the team names exactly as given, and keep the humor good-natured. Don't draw
real people, real NFL players, or NFL team logos, and don't use racial or ethnic stereotypes or caricatures, even
when a team name mentions a nationality or ethnicity."""


def matchups(results):
    """(winner, loser) pairs for every game, with GUSBOT's game last using its official score."""
    games = defaultdict(list)
    for team in results["teams"]:
        if team["owner"] != BOT_USERNAME and team["matchup_id"] is not None:
            games[team["matchup_id"]].append(team)

    bot_opponent = results["opponent"]
    pairs = []
    for teams in games.values():
        if bot_opponent not in teams:
            pairs.append(tuple(sorted(teams, key=lambda team: team["points"], reverse=True)))

    bot = {**results["bot"], "team_name": "GUSBOT", "points": results["bot_score"]}
    pairs.append((bot, bot_opponent) if results["bot_won"] else (bot_opponent, bot))
    return pairs


def fetch_players():
    """Sleeper's player ID -> "Name (POS)", or {} when the download fails, so the report goes out without player stats."""
    try:
        players = get_json("/players/nfl")
    except requests.RequestException as error:
        print(f"Couldn't fetch the player list, leaving out player stats: {error}", file=sys.stderr)
        return {}
    return {player_id: f"{player.get('first_name', '')} {player.get('last_name', '')} ({player.get('position')})".strip()
            for player_id, player in players.items()}


def best_and_worst(team, players):
    """The team's best and worst starter as a sentence for the model, or "" without player data."""
    starters = [(players[player_id], points) for player_id, points in team.get("starters", []) if player_id in players]
    if not starters:
        return ""
    best = max(starters, key=lambda starter: starter[1])
    worst = min(starters, key=lambda starter: starter[1])
    line = f" {team['team_name']}'s best starter: {best[0]} {best[1]:.2f}"
    if worst is not best:
        line += f"; worst starter: {worst[0]} {worst[1]:.2f}"
    return line + "."


def matchup_lines(results, players):
    """Plain-text line for each matchup, in the order of matchups(), used as the model's input and as the fallback."""
    games = matchups(results)
    lines = []
    for a, b in games[:-1]:
        lines.append(f"{a['team_name']} ({a['owner']}) {a['points']:.2f} def. "
                     f"{b['team_name']} ({b['owner']}) {b['points']:.2f}."
                     f"{best_and_worst(a, players)}{best_and_worst(b, players)}")

    bot_opponent = results["opponent"]
    lines.append(f"GUSBOT game: GUSBOT {results['bot_score']:.2f} vs. "
                 f"{bot_opponent['team_name']} ({bot_opponent['owner']}) {bot_opponent['points']:.2f}. "
                 f"The median GUSBOT's opponent had to beat was {results['median']:.2f}. "
                 f"{result_line(results)}."
                 + "".join(best_and_worst(team, players) for team in games[-1]))
    return lines


def standings_table(records, week):
    """The standings as a Discord code block, so the columns line up."""
    rows = [f"{'#':>2}  {'Team':<24} {'W-L':>5}"]
    for rank, record in enumerate(records, 1):
        name = "GUSBOT" if record["owner"] == BOT_USERNAME else record["team_name"]
        wins_losses = f"{record['wins']}-{record['losses']}" + (f"-{record['ties']}" if record["ties"] else "")
        rows.append(f"{rank:>2}  {name[:24]:<24} {wins_losses:>5}")
    return f"**Standings after Week {week}**\n```\n" + "\n".join(rows) + "\n```"


def score_line(winner, loser):
    return f"**{winner['team_name']}** {winner['points']:.2f} def. **{loser['team_name']}** {loser['points']:.2f}"


def post_with_retry(url, headers, payload, timeout):
    """POST to a model API, retrying when it's overloaded or rate-limited."""
    for delay in RETRY_DELAYS + [None]:
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as error:
            if delay is None:
                raise
            print(f"Model request failed ({error}), retrying in {delay}s", file=sys.stderr)
        else:
            if response.status_code not in RETRY_STATUSES or delay is None:
                break
            print(f"Model returned {response.status_code}, retrying in {delay}s", file=sys.stderr)
        time.sleep(delay)
    if not response.ok:
        print(f"Model error response: {response.text[:500]}", file=sys.stderr)
    response.raise_for_status()
    return response.json()


def write_recap(lines, api_key, base_url, model):
    """Return (headline, [recap for each matchup]) written by the model."""
    summary = "\n".join(f"{number}. {line}" for number, line in enumerate(lines, 1))
    response = post_with_retry(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        payload={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": summary},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    content = response["choices"][0]["message"]["content"].strip()
    # Some models wrap JSON in a code fence even when asked not to
    content = content.removeprefix("```json").removeprefix("```").removesuffix("```")
    recap = json.loads(content)
    headline, recaps = recap["headline"], recap["matchups"]
    if not isinstance(headline, str) or not isinstance(recaps, list) or len(recaps) != len(lines) \
            or not all(isinstance(text, str) for text in recaps):
        raise ValueError(f"Expected a headline and {len(lines)} matchup recaps, got: {content[:200]}")
    return headline.strip(), [text.strip() for text in recaps]


def draw_manga(week, winner, loser, api_key, model):
    """Draw a manga of one matchup with Nano Banana and return the JPEG bytes."""
    prompt = MANGA_PROMPT.format(
        week=week,
        winner=winner["team_name"], winner_points=winner["points"],
        loser=loser["team_name"], loser_points=loser["points"],
    )
    interaction = post_with_retry(
        GEMINI_INTERACTIONS_URL,
        headers={"x-goog-api-key": api_key},
        payload={
            "model": model,
            "input": prompt,
            "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "3:4", "image_size": "1K"},
            "store": False,
        },
        timeout=180,
    )
    for step in interaction.get("steps", []):
        if step.get("type") == "model_output":
            for block in step.get("content", []):
                if block.get("type") == "image" and block.get("data"):
                    return base64.b64decode(block["data"])
    raise ValueError(f"No image in the response (status: {interaction.get('status')})")


def draw_mangas(results, api_key, model):
    """Return JPEG bytes for each matchup, in the order of matchups(), or None where the manga failed."""
    mangas = []
    for winner, loser in matchups(results):
        try:
            mangas.append(draw_manga(results["week"], winner, loser, api_key, model))
        except (requests.RequestException, ValueError) as error:
            print(f"Manga failed for {winner['team_name']} vs. {loser['team_name']}: {error}", file=sys.stderr)
            mangas.append(None)
    return mangas


def post_to_discord(webhook_url, content, image=None):
    """Post a message, with a manga attached when one is given."""
    if len(content) > DISCORD_LIMIT:
        content = content[:DISCORD_LIMIT - 1] + "…"
    if image is None:
        response = requests.post(webhook_url, json={"content": content}, timeout=30)
    else:
        response = requests.post(webhook_url, data={"payload_json": json.dumps({"content": content})},
                                 files={"files[0]": ("manga.jpg", image, "image/jpeg")}, timeout=60)
    response.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", type=int, help="week to report on (default: the last completed week)")
    parser.add_argument("--dry-run", action="store_true", help="print the recap instead of posting it")
    parser.add_argument("--no-fallback", action="store_true",
                        help="exit with an error instead of posting the plain summary when the model call fails")
    parser.add_argument("--no-manga", action="store_true", help="skip the matchup manga")
    parser.add_argument("--manga-dir", default="manga",
                        help="where --dry-run saves the manga (default: %(default)s)")
    args = parser.parse_args()

    # Sleeper moves to the next week once Monday night's game ends, so the last completed week is one behind.
    week = args.week or current_nfl_week() - 1
    if week < 1:
        print("No completed week to report on yet")
        return

    try:
        results = week_results(LEAGUE_ID, week)
    except ValueError as error:
        # Off-season, playoffs without GUSBOT, or a week with no scores
        print(f"Skipping report: {error}")
        return

    lines = matchup_lines(results, fetch_players())
    standings_post = standings_table(standings(LEAGUE_ID, week), week)
    headline, recaps = f"**Jager League: Week {week}**", lines
    api_key = os.environ.get("LLM_API_KEY")
    if api_key:
        try:
            headline, recaps = write_recap(lines, api_key,
                                           os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL,
                                           os.environ.get("LLM_MODEL") or DEFAULT_MODEL)
            # The GUSBOT result is the point of the report, so never rely on the model to state it.
            recaps[-1] += f"\n\n🤖 {result_line(results)}"
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as error:
            if args.no_fallback:
                sys.exit(f"Model call failed: {error}")
            print(f"Model call failed, posting the plain summary instead: {error}", file=sys.stderr)
    elif args.no_fallback:
        sys.exit("LLM_API_KEY is not set")
    else:
        print("LLM_API_KEY not set, posting the plain summary", file=sys.stderr)

    # Draw every manga before posting anything, so a failed run never leaves a half-posted report
    games = matchups(results)
    mangas = [None] * len(games)
    if api_key and not args.no_manga:
        mangas = draw_mangas(results, api_key, os.environ.get("IMAGE_MODEL") or DEFAULT_IMAGE_MODEL)
    # Each matchup is one message: its score, its recap, and its manga attached.
    # The plain summary lines already state the score.
    posts = [(text if recaps is lines else f"{score_line(winner, loser)}\n{text}", image)
             for (winner, loser), text, image in zip(games, recaps, mangas)]

    if args.dry_run:
        print(headline)
        manga_dir = pathlib.Path(args.manga_dir)
        for number, (content, image) in enumerate(posts, 1):
            print(f"\n{content}")
            if image is not None:
                manga_dir.mkdir(parents=True, exist_ok=True)
                path = manga_dir / f"week{week}-matchup{number}.jpg"
                path.write_bytes(image)
                print(f"[manga: {path}]")
        print(f"\n{standings_post}")
        return

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        sys.exit("DISCORD_WEBHOOK_URL is not set")
    post_to_discord(webhook_url, headline)

    # The headline is already posted, so a failed post is logged rather than failing the run,
    # which would make the workflow retry and post the report twice.
    for content, image in posts:
        try:
            post_to_discord(webhook_url, content, image)
        except requests.RequestException as error:
            print(f"Posting matchup failed for {content.splitlines()[0]}: {error}", file=sys.stderr)
    try:
        post_to_discord(webhook_url, standings_post)
    except requests.RequestException as error:
        print(f"Posting the standings failed: {error}", file=sys.stderr)
    print(f"Posted week {week} recap to Discord with {sum(image is not None for _, image in posts)} manga")


if __name__ == "__main__":
    main()

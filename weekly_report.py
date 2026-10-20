"""Write the weekly Jager League recap with an LLM and post it to Discord, with a manga for each matchup.

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

from JagerLeagueBotScoreCalculator import BOT_USERNAME, LEAGUE_ID, current_nfl_week, result_line, week_results

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-3.8-flash"
GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_IMAGE_MODEL = "gemini-nano-banana-2.1"
DISCORD_LIMIT = 2000
# Seconds to wait before each retry when the model is overloaded or rate-limited
RETRY_DELAYS = [10, 30, 60]
RETRY_STATUSES = {429, 500, 502, 503, 504}

SYSTEM_PROMPT = """You write the weekly recap for the Jager League, a 10-team fantasy football league among friends.
One slot is filled by a bot, GUSBOT, whose real score doesn't count. Its official score is the median of the
other teams' scores, not counting its opponent. Write a short recap for Discord in the voice of a
SportsCenter highlights anchor, in the style of Scott Van Pelt and Chris "Boomer" Berman: dry, deadpan
sympathy for blowout losers and bad beats, over-the-top play-by-play energy for big scores, and playful
puns on team names. Keep it slightly comedic and good-natured: rib the losers, but don't be mean. Don't claim
to be either anchor or quote their catchphrases word for word.

Format: a headline, one or two lines per matchup, and the GUSBOT result. Use only the scores given and don't
invent player stats. Use Discord markdown and keep it under 1500 characters."""

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
    """(winner, loser) pairs for every game, with GUSBOT's game last using its official median score."""
    games = defaultdict(list)
    for team in results["teams"]:
        if team["owner"] != BOT_USERNAME and team["matchup_id"] is not None:
            games[team["matchup_id"]].append(team)

    bot_opponent = results["opponent"]
    pairs = []
    for teams in games.values():
        if bot_opponent not in teams:
            pairs.append(tuple(sorted(teams, key=lambda team: team["points"], reverse=True)))

    bot = {"team_name": "GUSBOT", "owner": BOT_USERNAME, "points": results["bot_score"]}
    pairs.append((bot, bot_opponent) if results["bot_won"] else (bot_opponent, bot))
    return pairs


def matchup_summary(results):
    """Plain-text summary of the week, used as the model's input and as the fallback post."""
    lines = [f"**Jager League: Week {results['week']}**"]
    bot_opponent = results["opponent"]
    for a, b in matchups(results)[:-1]:
        lines.append(f"{a['team_name']} ({a['owner']}) {a['points']:.2f} def. "
                     f"{b['team_name']} ({b['owner']}) {b['points']:.2f}")

    lines.append(f"GUSBOT game: GUSBOT {results['bot_score']:.2f} vs. "
                 f"{bot_opponent['team_name']} ({bot_opponent['owner']}) {bot_opponent['points']:.2f}. "
                 f"{result_line(results)}")
    return "\n".join(lines)


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


def write_recap(summary, api_key, base_url, model):
    response = post_with_retry(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        payload={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": summary},
            ],
        },
        timeout=60,
    )
    return response["choices"][0]["message"]["content"].strip()


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
    """Return (caption, JPEG bytes) for each matchup. A matchup whose manga fails is left out."""
    mangas = []
    for winner, loser in matchups(results):
        caption = (f"**{winner['team_name']}** {winner['points']:.2f} def. "
                   f"**{loser['team_name']}** {loser['points']:.2f}")
        try:
            mangas.append((caption, draw_manga(results["week"], winner, loser, api_key, model)))
        except (requests.RequestException, ValueError) as error:
            print(f"Manga failed for {winner['team_name']} vs. {loser['team_name']}: {error}", file=sys.stderr)
    return mangas


def post_to_discord(webhook_url, content):
    if len(content) > DISCORD_LIMIT:
        content = content[:DISCORD_LIMIT - 1] + "…"
    response = requests.post(webhook_url, json={"content": content}, timeout=30)
    response.raise_for_status()


def post_image_to_discord(webhook_url, caption, image):
    response = requests.post(webhook_url, data={"payload_json": json.dumps({"content": caption})},
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

    summary = matchup_summary(results)
    recap = summary
    api_key = os.environ.get("LLM_API_KEY")
    if api_key:
        try:
            recap = write_recap(summary, api_key,
                                os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL,
                                os.environ.get("LLM_MODEL") or DEFAULT_MODEL)
            # The GUSBOT result is the point of the report, so never rely on the model to state it.
            recap += f"\n\n🤖 {result_line(results)}"
        except (requests.RequestException, KeyError, IndexError) as error:
            if args.no_fallback:
                sys.exit(f"Model call failed: {error}")
            print(f"Model call failed, posting the plain summary instead: {error}", file=sys.stderr)
    elif args.no_fallback:
        sys.exit("LLM_API_KEY is not set")
    else:
        print("LLM_API_KEY not set, posting the plain summary", file=sys.stderr)

    # Draw every manga before posting anything, so a failed run never leaves a half-posted report
    mangas = []
    if api_key and not args.no_manga:
        mangas = draw_mangas(results, api_key, os.environ.get("IMAGE_MODEL") or DEFAULT_IMAGE_MODEL)

    if args.dry_run:
        print(recap)
        if mangas:
            manga_dir = pathlib.Path(args.manga_dir)
            manga_dir.mkdir(parents=True, exist_ok=True)
            for number, (caption, image) in enumerate(mangas, 1):
                path = manga_dir / f"week{week}-matchup{number}.jpg"
                path.write_bytes(image)
                print(f"{caption}: {path}")
        return

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        sys.exit("DISCORD_WEBHOOK_URL is not set")
    post_to_discord(webhook_url, recap)
    print(f"Posted week {week} recap to Discord")

    # The recap is already posted, so a failed upload is logged rather than failing the run,
    # which would make the workflow retry and post the recap twice.
    for caption, image in mangas:
        try:
            post_image_to_discord(webhook_url, caption, image)
        except requests.RequestException as error:
            print(f"Posting manga failed for {caption}: {error}", file=sys.stderr)
    print(f"Posted {len(mangas)} manga to Discord")


if __name__ == "__main__":
    main()

"""Thin client for the public, read-only Sleeper API (no auth required)."""

import json
import os
import time

import requests

BASE_URL = "https://api.sleeper.app/v1"

# Sleeper asks that /players/nfl (~5MB) be fetched at most once a day.
PLAYERS_CACHE = os.path.join(os.path.dirname(__file__), "..", ".cache", "players_nfl.json")
PLAYERS_MAX_AGE = 24 * 60 * 60


def _get(path):
    response = requests.get(f"{BASE_URL}{path}", timeout=30)
    response.raise_for_status()
    return response.json()


def nfl_state():
    return _get("/state/nfl")


def league(league_id):
    return _get(f"/league/{league_id}")


def users(league_id):
    return _get(f"/league/{league_id}/users")


def rosters(league_id):
    return _get(f"/league/{league_id}/rosters")


def matchups(league_id, week):
    return _get(f"/league/{league_id}/matchups/{week}")


def players(cache_path=PLAYERS_CACHE):
    if os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < PLAYERS_MAX_AGE:
        with open(cache_path) as f:
            return json.load(f)
    data = _get("/players/nfl")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(data, f)
    return data


def fetch_week(league_id, week):
    """Everything needed to analyse one week, in one dict (also the fixture format)."""
    return {
        "week": week,
        "league": league(league_id),
        "users": users(league_id),
        "rosters": rosters(league_id),
        "matchups": matchups(league_id, week),
        "players": players(),
    }

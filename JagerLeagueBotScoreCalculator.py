import argparse
import os

from jagerbot import sleeper
from jagerbot.week import find_bot_roster_id, bot_score

parser = argparse.ArgumentParser(description="Work out GUSBOT's score and result for a week.")
parser.add_argument("--week", type=int, help="Week to score (prompted for if omitted)")
args = parser.parse_args()

league = os.environ.get("JAGER_LEAGUE_ID") or input("Sleeper league ID for this season: ")
fantasy_week = int(sleeper.nfl_state()['week'])

current_week = args.week or int(input("LMK which week you're interested in seeing data for homie : "))
while (current_week > fantasy_week) :
    print ("Sheeeesh I can't predict the future.... yet \n")
    current_week = int((input("Wanna try again and give me an actual week: ")))

matchups = sleeper.matchups(league, current_week)
rosters = sleeper.rosters(league)
users = sleeper.users(league)

bot_roster_id = find_bot_roster_id(users, rosters, matchups)
if bot_roster_id is None:
    raise SystemExit("Couldn't find GUSBOT's roster this week.")

bot_points, opponent = bot_score(matchups, bot_roster_id)
if opponent is None:
    raise SystemExit("GUSBOT doesn't have an opponent this week.")
bot_op_score = float(opponent['points'] or 0)

owner_id = next(r['owner_id'] for r in rosters if r['roster_id'] == opponent['roster_id'])
bot_op_name = next((u['display_name'] for u in users if u['user_id'] == owner_id), "Wow")

#Announce the winner of the Bot Game
if (bot_op_score < bot_points) :
    print('GUSBOT beat '+ str(bot_op_name) + ' with the score of ' + str(bot_points) + ' to ' + str(bot_op_score))
else:
    print (str(bot_op_name) + ' beat GUSBOT with a score of ' + str(bot_op_score) + ' to ' + str(bot_points))

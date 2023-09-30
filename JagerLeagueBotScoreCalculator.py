import requests
import statistics
import json

#test league and week
# league = 865826998382112768
#current_week = 3

# Get the current week
# variable: current_week
# Jager Sleeper League: league 


url_nfl_state= 'https://api.sleeper.app/v1/state/nfl'
response = requests.get(url_nfl_state)
#3current_week = response.json()['week']
league = 1001613023221522432

current_week = int(input("LMK which week you're interested in seeing data for homie : "))
list_matchups_data = []
user_data = []
roster_data = []
points = []

target_matchup = "False"
bot_op_score = "DickenCider"
bot_op_id = 0
bot_op_owner_id = 0 
bot_op_name ="Wow"
# get matchup endpoint

url_matchups =f"https://api.sleeper.app/v1/league/{league}/matchups/{current_week}"
matchups_response = requests.get(url_matchups)
json_matchups = matchups_response.json()

#find the bot score
for matchup in json_matchups:
    list_matchups_data.append([league, matchup['matchup_id'], matchup['roster_id'], matchup['points']])  

    if(int(float(matchup['points'])) == 0):
        target_matchup = str(matchup['matchup_id'])

#Find the right bot opponent
for matchup in json_matchups:
    if(int(float(matchup['points'])) == 0):
        continue
    elif(target_matchup == str(matchup['matchup_id'])):
        bot_op_id = str(matchup['roster_id'])
        bot_op_score = float(matchup['points'])
        points.append(matchup['points'])
    else :
        points.append(matchup['points'])

points = [str(p) for p in points]

for i in range(0, len(points)):
    points[i] = float(points[i])


#Roster API Call to get the Bot Opponent's Owner ID
url_rosters = f"https://api.sleeper.app/v1/league/{league}/rosters"
roster_response = requests.get(url_rosters)
json_rosters = roster_response.json()

for roster in json_rosters : 
    roster_data.append([roster['roster_id'], roster['owner_id']])
    if (bot_op_id == str(roster['roster_id'])) :
        bot_op_owner_id = str(roster['owner_id'])

#Users API call to get the Bot Opponent's Owner Display Name
url_users = f"https://api.sleeper.app/v1/league/{league}/users"
user_response = requests.get(url_users)
json_users = user_response.json()

for users in json_users :
    user_data.append([users['user_id'], users['display_name'] ]) 
    if (bot_op_owner_id == str(users['user_id'])) :
        bot_op_name = str(users['display_name'])

# get scores and return median
bot_score = statistics.median(points)

#Announce the winner of the Bot Game
if (bot_op_score < bot_score) :
    print('GUSBOT beat '+ str(bot_op_name) + ' with the score of ' + str(bot_score) + ' to ' + str(bot_op_score))
else:
    print (str(bot_op_name) + ' beat GUSBOT with a score of ' + str(bot_op_score) + ' to ' + str(bot_score))


## TESTING ##

#test Json response data 
#print(user_data)
#print("roster")
#print(roster_data)
#print("matchups")
#print(list_matchups_data)
#print(target_matchup)

#print (points)
#print (bot_score)
# print (target_matchup)
# print (bot_op_score)
# print (bot_op_name)
#print('The Median is '+ str(bot_score) + '.')
#print(y)
#test print 
#print(*list_matchups_data, sep = "\n")
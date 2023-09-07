import requests

#test league and week
# league = 865826998382112768
# current_week = 12

# Get the current week
# variable: current_week
# Jager Sleeper League: league 


url_nfl_state= 'https://api.sleeper.app/v1/state/nfl'
response = requests.get(url_nfl_state)
current_week = response.json()['week']
league = 1001613023221522432

list_matchups_data = []
points = 0
        
# get matchup endpoint

url_matchups =f"https://api.sleeper.app/v1/league/{league}/matchups/{current_week}"
matchups_response = requests.get(url_matchups)
json_matchups = matchups_response.json()

for matchup in json_matchups:
    list_matchups_data.append([league, matchup['roster_id'], matchup['points']])  
    points = points + int(matchup['points'])
# get scores and return average

bot_score = points/7

#test print 
#print(*list_matchups_data, sep = "\n")

#return average
print(bot_score)
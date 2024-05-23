from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
import pymongo
import os
from dotenv import load_dotenv
import logging

load_dotenv()

DB_HOST = os.getenv("DB_CONNECTION")
DB_NAME = os.getenv("DB_NAME")

app = Flask(__name__)
app.config['MONGO_URI'] = DB_HOST
app.config['SECRET_KEY'] = 'gnawhs'  # Set this to a random string!

mongo = pymongo.MongoClient(app.config['MONGO_URI'])
db = mongo[DB_NAME]
users_collection = db["streamlit_users"]
draft_collection = db["draft"]

### methods ########################################
def create_roster_collection_2023():
  ### uncomment this to override the collection protection lock
  upcoming_season_collection.delete_many({})

  # Only reset collection if lock not present
  try:
    check_lock = upcoming_season_collection.find_one( {"collection_lock": True } )
    if check_lock:
      print("Sorry, cannot delete this collection. Collection is currently locked.\nSee create_roster_collection_2023().")
      return

    upcoming_season_collection.delete_many({})

  except ConnectionError as e:
    print(f"An error occurred: {e}")

  # Only get players under contract for next season
  players_under_contract = list(franchise_tag_collection.find({"contract.y1_cost": {"$exists":True}}))

  players_under_contract_list = []
  for player in players_under_contract:
    del(player['_id'])
    player['season'] = upcoming_season
    player['needs_contract_status']=False
    # print(json.dumps(player, indent=2))
    player['contract']['y0_cost'] = player['contract']['y1_cost']
    del(player['contract']['y1_cost'])
    player['contract']['contract_years_left'] = 1
    player['contract']['free_agent_before_season'] = upcoming_season + 1
    if player['contract'].get('y2_cost') is not None:
      player['contract']['y1_cost'] = player['contract']['y2_cost']
      del(player['contract']['y2_cost'])
      player['contract']['contract_years_left'] = 2
      player['contract']['free_agent_before_season'] = upcoming_season + 2
    players_under_contract_list.append(player)

  upcoming_season_collection.insert_many(players_under_contract_list)

def updated_contract_activated_taxi_squad():
  taxi_players = franchise_tag_collection.find({"contract.taxi_designation":True})
  print(taxi_players)
  for player in taxi_players:
    franchise_tag_collection.update_one({ "player_name": player['player_name'], "contract.taxi_designation": True },
                                        { "$set": { 'contract.y3_cost': player['contract']['y2_cost'],
                                                    'contract.y2_cost': player['contract']['y1_cost'],
                                                    'contract.y1_cost': player['contract']['y0_cost'],
                                                    'contract.contract_years_left': player['contract']['contract_years_left']+1,
                                                    'contract.free_agent_before_season': player['contract']['free_agent_before_season']+1,
                                                    "contract.taxi_designation": False } } )
### CHANGE ME ########################################
current_season = 2023
upcoming_season = 2024
upcoming_season_collection = db[f"roster_{upcoming_season}"]
franchise_tag_collection = db[f"roster_{upcoming_season}_ft"]

# resets the collection
# create_upcoming_season_collection(next_year=upcoming_season)

create_roster_collection_2023()
######################################################

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.session_protection = "strong"

class User(UserMixin):
    def __init__(self, user_id, username, admin_status=False):
        self.id = user_id
        self.username = username
        self.admin_status = admin_status

@login_manager.user_loader
def load_user(user_id):
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        return User(str(user['_id']), user['username'], user['admin_status'])
    return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = users_collection.find_one({'username': username})
        if user and check_password_hash(user['password'], password):
            user_obj = User(str(user['_id']), user['username'], user['admin_status'])
            login_user(user_obj)
            flash('Login successful!', 'success')
            return redirect(url_for("landing"))
        else:
            flash('Invalid username or password. Please try again.', 'danger')

    return render_template('login.html')

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('login'))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        name = request.form.get("name")
        email = request.form.get("email")
        existing_user = users_collection.find_one({"$or": [{"username": username}, {"email": email}]})
        if existing_user is None:
            hashed_password = generate_password_hash(password)
            users_collection.insert_one({
                "username": username,
                "password": hashed_password,
                "name": name,
                "email": email,
                "admin_status": False
            })
            return redirect(url_for("login"))
        flash("Username and/or email already exists.", "danger")
    return render_template("register.html")

@app.route("/")
@app.route("/home")
@login_required
def landing():
    return render_template("home.html")

@app.route("/about")
@login_required
def about():
    return render_template("about.html")


@app.route("/draftresults")
@login_required
def draft_results():
    seasons = draft_collection.distinct("season")
    latest_year = max(seasons) if seasons else None

    users_list = list(users_collection.find({"username": {"$exists": True}}))
    users = {u['username']: u['admin_status'] for u in users_list}

    draft = list(draft_collection.aggregate([
        {"$match": {"player_name": {"$exists": True}}},
        {"$project": {
            "_id": 1,
            "season": 1,
            "draft_type": 1,
            "pick_no": 1,
            "player_name": 1,
            "team_name": 1,
            "needs_contract_status": 1,
            "position": "$metadata.position",
            "contract_y0_cost": {"$ifNull": ["$contract.y0_cost", 0]},
            "contract_y1_cost": {"$ifNull": ["$contract.y1_cost", 0]},
            "contract_y2_cost": {"$ifNull": ["$contract.y2_cost", 0]},
            "contract_years_left": "$contract.contract_years_left",
            "free_agent_before_season": "$contract.free_agent_before_season",
        }}
    ]))

    for item in draft:
        contract_y0_cost = item.get('contract_y0_cost', 0)
        contract_y1_cost = item.get('contract_y1_cost', 0)
        contract_y2_cost = item.get('contract_y2_cost', 0)

        if contract_y2_cost > contract_y0_cost:
            item['slider_position'] = 3
        elif contract_y1_cost > contract_y0_cost:
            item['slider_position'] = 2
        else:
            item['slider_position'] = 1

    current_username = current_user.username
    return render_template("draft_results.html",
                           seasons=seasons,
                           users=users.keys(),
                           results=draft,
                           title="Set player contracts",
                           latest_year=latest_year,
                           current_username=current_username,
                           admin_status=users.get(current_username))

@app.route("/setcontracts")
@login_required
def set_contracts():
    seasons = upcoming_season_collection.distinct("season")
    latest_year = max(seasons) if seasons else None

    users_list = list(users_collection.find({"username": {"$exists": True}}))
    users = {u['username']: u['admin_status'] for u in users_list}

    season_collection = list(upcoming_season_collection.aggregate([
        {"$match": {"player_name": {"$exists": True}}},
        {"$project": {
            "_id": 1,
            "season": 1,
            "draft_type": 1,
            "pick_no": 1,
            "player_name": 1,
            "team_name": 1,
            "needs_contract_status": 1,
            "position": "$metadata.position",
            "contract_y0_cost": {"$ifNull": ["$contract.y0_cost", 0]},
            "contract_y1_cost": {"$ifNull": ["$contract.y1_cost", 0]},
            "contract_y2_cost": {"$ifNull": ["$contract.y2_cost", 0]},
            "contract_years_left": "$contract.contract_years_left",
            "free_agent_before_season": "$contract.free_agent_before_season",
        }},
        {"$sort": {"team_name": 1} }
    ]))

    for item in season_collection:
        contract_y0_cost = item.get('contract_y0_cost', 0)
        contract_y1_cost = item.get('contract_y1_cost', 0)
        contract_y2_cost = item.get('contract_y2_cost', 0)

        if contract_y2_cost > contract_y0_cost:
            item['slider_position'] = 3
        elif contract_y1_cost > contract_y0_cost:
            item['slider_position'] = 2
        else:
            item['slider_position'] = 1

    current_username = current_user.username
    return render_template("contracts.html",
                           seasons=seasons,
                           users=users.keys(),
                           results=season_collection,
                           title="Set player contracts",
                           latest_year=latest_year,
                           current_username=current_username,
                           admin_status=users.get(current_username))

@app.route("/updatecontracts", methods=['POST'])
@login_required
def update_draft():
    data = request.json
    for item in data:
        update_data = {'needs_contract': False}
        if 'y1' in item and item['y1'] is not None:
            update_data['contract.y1_cost'] = item['y1']
        if 'y2' in item and item['y2'] is not None:
            update_data['contract.y2_cost'] = item['y2']

        if update_data:
            draft_collection.update_many(
                {"_id": ObjectId(item["_id"])},
                {"$set": update_data}
            )
    return jsonify({"message": "Data updated successfully!"}), 200



@app.route("/setfranchisetags")
@login_required
def set_franchise_tag():
    users_list = list(users_collection.find({"username": {"$exists": True}}))
    users = {u['username']: u['admin_status'] for u in users_list}

    roster = list(franchise_tag_collection.find({"contract": {"$exists": True}}, {
        "_id": 1,
        "season": 1,
        "player_name": 1,
        "team_name": 1,
        "position": "$metadata.position",
        "contract_y0_cost": {"$ifNull": ["$contract.y0_cost", 0]},
        "contract_y1_cost": {"$ifNull": ["$contract.y1_cost", 0]},
        "contract_y2_cost": {"$ifNull": ["$contract.y2_cost", 0]},
        "contract_years_left": "$contract.contract_years_left",
        "free_agent_before_season": "$contract.free_agent_before_season",
        "franchise_tag_allowed": "$contract.franchise_tag_allowed"
    }).sort([("team_name", 1)]))

    current_username = current_user.username
    return render_template("franchise_tags.html",
                           seasons=[2023],
                           users=users.keys(),
                           results=roster,
                           title="Set franchise tag(s)",
                           latest_year=2023,
                           current_username=current_username,
                           admin_status=users.get(current_username))

@app.route('/updatefranchisetags', methods=['POST'])
@login_required
def update_franchise_tags():
    data = request.json
    updates = data.get('updates', [])
    ids_to_update = data.get('ids_to_update', [])

    franchise_tag_collection.update_many(
        {"_id": {"$in": [ObjectId(_id) for _id in ids_to_update]}},
        {"$set": {"contract.franchise_tag_allowed": False}}
    )

    # franchise_tag_collection.update_many({}, {"$set": {"collection_delete_lock": True}})
    create_roster_collection_2023()

    for item in updates:
        update_data = {}
        if 'franchise_cost' in item and item['franchise_cost'] is not None:
            update_data['contract.y1_cost'] = item['franchise_cost']
            update_data['contract.franchise_tag_allowed'] = False
            update_data['contract.franchise_tag_used'] = True

        if update_data:
            franchise_tag_collection.update_one(
                {"_id": ObjectId(item["_id"])},
                {"$set": update_data}
            )
    return jsonify({"message": "Data updated successfully!"}), 200




@app.route("/managetaxisquad")
@login_required
def manage_taxi_squad():
    users_list = list(users_collection.find({"username": {"$exists": True}}))
    users = {u['username']: u['admin_status'] for u in users_list}

    roster = list(franchise_tag_collection.find({"contract.taxi_designation": {"$exists":True}}, {
        "_id": 1,
        "season": 1,
        "player_name": 1,
        "team_name": 1,
        "position": "$metadata.position",
        "contract_y0_cost": {"$ifNull": ["$contract.y0_cost", 0]},
        "contract_y1_cost": {"$ifNull": ["$contract.y1_cost", 0]},
        "contract_y2_cost": {"$ifNull": ["$contract.y2_cost", 0]},
        "contract_y3_cost": {"$ifNull": ["$contract.y3_cost", 0]},
        "contract_years_left": "$contract.contract_years_left",
        "free_agent_before_season": "$contract.free_agent_before_season",
        "taxi_designation": "$contract.taxi_designation"
    }).sort([("team_name", 1)]))

    current_username = current_user.username
    return render_template("taxi_squad.html",
                           seasons=[2024],
                           users=users.keys(),
                           results=roster,
                           title="Manage taxi squad",
                           latest_year=2024,
                           current_username=current_username,
                           admin_status=users.get(current_username))

@app.route('/updatetaxisquad', methods=['POST'])
@login_required
def update_taxi_squad():
    data = request.json
    for item in data:
        _id = item.get('_id')
        y0_cost = item.get('y0_cost')
        y1_cost = item.get('y1_cost')
        y2_cost = item.get('y2_cost')
        contract_years_left = item.get('contract_years_left')
        free_agent_before_season = item.get('free_agent_before_season')
        if _id:
            update_data = {
                "contract.taxi_designation": False,
                "contract.y0_cost": y0_cost,
                "contract.y1_cost": y1_cost,
                "contract.y2_cost": y2_cost,
                "contract.contract_years_left": contract_years_left,
                "contract.free_agent_before_season": free_agent_before_season
            }
            unset_data = {
                "contract.y3_cost": ""
            }
            franchise_tag_collection.update_one(
                {"_id": ObjectId(_id)},
                {"$set": update_data, "$unset": unset_data}
            )
    updated_contract_activated_taxi_squad()

    return jsonify({"message": "Taxi squad updated successfully!"}), 200




@app.route("/calculator")
@login_required
def calculator():
    seasons = upcoming_season_collection.distinct("season")
    users = upcoming_season_collection.distinct("team_name")
    pipeline = [
        {
            "$group": {
                "_id": None,
                "maxSeason": {"$max": "$season"}
            }
        },
        {
            "$lookup": {
                "from": upcoming_season_collection.name,
                "let": {"max_season": "$maxSeason"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$gte": ["$season", 2021]},
                                    {"$eq": ["$season", "$$max_season"]}
                                ]
                            }
                        }
                    },
                    {
                        "$project": {
                            "_id": 1,
                            "season": 1,
                            "draft_type": 1,
                            "pick_no": 1,
                            "player_name": 1,
                            "team_name": 1,
                            "needs_contract": 1,
                            "position": "$metadata.position",
                            "contract_y0_cost": {"$ifNull": ["$contract.y0_cost", 0]},
                            "contract_y1_cost": {"$ifNull": ["$contract.y1_cost", 0]},
                            "contract_y2_cost": {"$ifNull": ["$contract.y2_cost", 0]},
                            "contract_years_left": "$contract.contract_years_left",
                            "free_agent_before_season": "$contract.free_agent_before_season"
                        }
                    }
                ],
                "as": "drafts"
            }
        },
        {
            "$unwind": "$drafts"
        },
        {
            "$replaceRoot": {"newRoot": "$drafts"}
        }
    ]

    draft = list(upcoming_season_collection.aggregate(pipeline))

    latest_year = max(seasons) if seasons else None
    current_username = current_user.username
    return render_template("calculator.html",
                           users=users,
                           results=draft,
                           title="set contract",
                           current_username=current_username)

if __name__ == '__main__':
    app.run(debug=True)
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from bson.objectid import ObjectId
import pymongo
import os
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.DEBUG)
load_dotenv()

DB_HOST = os.getenv("DB_CONNECTION")
DB_NAME=os.getenv("DB_NAME")

app = Flask(__name__)
app.config['MONGO_URI'] = DB_HOST
app.config['SECRET_KEY'] = 'gnawhs'  # Set this to a random string!

mongo = pymongo.MongoClient(app.config['MONGO_URI'])
db = mongo[DB_NAME]
users_collection = db["streamlit_users"]
draft_collection = db["draft"]

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.session_protection = "strong"  # Can be 'strong', 'basic', or None

class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        return User(str(user['_id']), user['username'])
    return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Fetch the user by username
        user = users_collection.find_one({'username': username})
        if user and check_password_hash(user['password'], password):
            # Create user object for Flask-Login
            user_obj = User(str(user['_id']), user['username'])
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
        existing_user = users_collection.find_one({ "$or": [ {"username": username}, {"email": email} ] } )
        if existing_user is None:
            hashed_password = generate_password_hash(password)
            users_collection.insert_one({ 
                                            "username": username, 
                                            "password": hashed_password,
                                            "name": name,
                                            "email": email
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

@app.route("/setcontracts")
@login_required
def set_contracts():
    seasons = draft_collection.distinct("season")
    users = draft_collection.distinct("team_name")
    draft = list(draft_collection.find({}, {
                "_id": 1, 
                "season": 1, 
                "draft_type": 1, 
                "pick_no": 1, 
                "player_name": 1, 
                "team_name": 1,
                "needs_contract":1,
                "position": "$metadata.position",
                "contract_y0_cost": "$contract.y0_cost",
                "contract_y1_cost": {"$ifNull": ["$contract.y1_cost", 0]},
                "contract_y2_cost": {"$ifNull": ["$contract.y2_cost", 0]},
                "contract_years_left": "$contract.contract_years_left",
                "free_agent_before_season": "$contract.free_agent_before_season",
                }))
    
    # Add slider settings
    for item in draft:
        if item['contract_y2_cost'] > item['contract_y0_cost']:
            item['slider_position'] = 3
        elif item['contract_y1_cost'] > item['contract_y0_cost']:
            item['slider_position'] = 2
        else:
            item['slider_position'] = 1

    if users:
        print("User found:", users)
    else:
        print("No user found.")
    latest_year = max(seasons) if seasons else None
    current_username = current_user.username
    return render_template("contracts.html", 
                           seasons=seasons,
                           users=users,
                           results=draft,
                           title="set contract",
                           latest_year=latest_year,
                           current_username=current_username)

@app.route("/updatecontracts", methods=['POST'])
@login_required
def update_draft():
    data = request.json
    for item in data:
        update_data = {}
        update_data['needs_contract'] = False
        if 'y1' in item and item['y1'] is not None:
            update_data['contract.y1_cost'] = item['y1']
        if 'y2' in item and item['y2'] is not None:
            update_data['contract.y2_cost'] = item['y2']
        
        logging.debug(update_data)
        if update_data:
            draft_collection.update_many(
                {"_id": ObjectId(item["_id"])},
                {"$set": update_data}
            )
    return jsonify({"message": "Data updated successfully!"}), 200

@app.route("/calculator")
def calculator():
    seasons = draft_collection.distinct("season")
    users = draft_collection.distinct("team_name")
    pipeline = [
        {
            "$group": {
                "_id": None,  # Grouping all documents together
                "maxSeason": {"$max": "$season"}  # Getting the maximum season
            }
        },
        {
            "$lookup": {
                "from": draft_collection.name,  # Refer back to the same collection
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
                            "contract_y0_cost": "$contract.y0_cost",
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
            "$unwind": "$drafts"  # Flatten the drafts array
        },
        {
            "$replaceRoot": {"newRoot": "$drafts"}  # Promote drafts documents to the top level
        }
    ]

    # Execute the aggregation pipeline
    draft = list(draft_collection.aggregate(pipeline))

    latest_year = max(seasons) if seasons else None
    current_username = current_user.username
    return render_template("calculator.html", 
                        #    seasons=seasons,
                           users=users,
                           results=draft,
                           title="set contract",
                        #    latest_year=latest_year,
                           current_username=current_username)

if __name__ == '__main__':
    app.run(debug=True)
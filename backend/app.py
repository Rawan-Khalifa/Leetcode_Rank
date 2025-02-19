from flask import Flask, jsonify
from dotenv import load_dotenv
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging
import os

# Load environment variables from .env
load_dotenv()

# Add this near the top of your file
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Ensure private key is formatted correctly
private_key = os.getenv("FIREBASE_PRIVATE_KEY")

# ✅ If private_key contains `\n`, it's stored correctly as a single line and needs conversion
if "\\n" in private_key:
    private_key = private_key.replace("\\n", "\n")

# Firebase setup using environment variables
cred = credentials.Certificate({
    "type": os.getenv("FIREBASE_TYPE"),
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
    "private_key": private_key,
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
    "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL"),
    "universe_domain": os.getenv("FIREBASE_UNIVERSE_DOMAIN")
})

firebase_admin.initialize_app(cred)
db = firestore.client()


# Function to fetch LeetCode rank
def fetch_leetcode_rank():
    username = "Rawan-Khalifa"
    url = "https://leetcode.com/graphql"
    headers = {"Content-Type": "application/json"}
    query = f"""
    {{
      matchedUser(username: "{username}") {{
        username
        profile {{
          ranking
        }}
      }}
    }}
    """

    response = requests.post(url, json={"query": query}, headers=headers)
    data = response.json()

    if data.get("data") and data["data"]["matchedUser"]:
        rank = data["data"]["matchedUser"]["profile"]["ranking"]
        print(f"Fetched rank: {rank}")

        # Store rank in Firebase Firestore
        db.collection("leetcode_rank").add({
            "rank": rank,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
    else:
        print("Failed to fetch LeetCode rank.")

# Schedule rank updates every 6 hours
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_leetcode_rank, "interval", hours=6)
scheduler.start()

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Welcome to the LeetCode Rank API",
        "endpoints": {
            "get_rank": "/api/rank"
        }
    })

@app.route("/api/rank", methods=["GET"])
def get_rank():
    try:
        logger.debug("Received request for rank data")
        ranks = db.collection("leetcode_rank").order_by(
            "timestamp", 
            direction=firestore.Query.DESCENDING
        ).limit(10).stream()
        
        data = []
        rank_count = 0
        
        for doc in ranks:
            doc_dict = doc.to_dict()
            rank_count += 1
            logger.debug(f"Processing rank document: {doc_dict}")
            data.append({
                "rank": doc_dict["rank"],
                "timestamp": doc_dict["timestamp"]
            })
        
        logger.info(f"Successfully retrieved {rank_count} rank records")
        
        if not data:
            logger.warning("No rank data found in database")
            return jsonify({
                "message": "No rank data available yet",
                "data": []
            }), 200
            
        return jsonify({
            "message": "Rank data retrieved successfully",
            "data": data
        })
        
    except Exception as e:
        logger.error(f"Error retrieving rank data: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Failed to retrieve rank data",
            "details": str(e)
        }), 500
    

@app.route("/api/fetch-now", methods=["GET"])
def trigger_fetch():
    """
    A testing endpoint that manually triggers rank fetching and returns the result immediately.
    This helps us verify the fetching process is working correctly.
    """
    try:
        username = "Rawan-Khalifa"
        url = "https://leetcode.com/graphql"
        headers = {"Content-Type": "application/json"}
        query = f"""
        {{
        matchedUser(username: "{username}") {{
            username
            profile {{
            ranking
            }}
        }}
        }}
        """

        response = requests.post(url, json={"query": query}, headers=headers)
        data = response.json()

        if data.get("data") and data["data"]["matchedUser"]:
            rank = data["data"]["matchedUser"]["profile"]["ranking"]
            
            # Store with more detailed information
            doc_ref = db.collection("leetcode_rank").document()
            doc_ref.set({
                "rank": rank,
                "timestamp": firestore.SERVER_TIMESTAMP,
                "fetch_time": datetime.now().isoformat()
            })
            
            return jsonify({
                "success": True,
                "message": "Rank fetched and stored successfully",
                "current_rank": rank,
            })
        else:
            return jsonify({
                "success": False,
                "message": "Failed to fetch LeetCode data",
                "response": data
            }), 400
            
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

@app.route("/api/rank/history", methods=["GET"])
def get_rank_history():
    """
    Enhanced endpoint that returns rank history with additional analytics
    """
    try:
        # Get all ranks ordered by timestamp
        ranks = db.collection("leetcode_rank") \
                 .order_by("timestamp", direction=firestore.Query.ASCENDING) \
                 .stream()
        
        data = []
        rank_values = []
        
        for doc in ranks:
            doc_dict = doc.to_dict()
            rank_values.append(doc_dict["rank"])
            data.append({
                "rank": doc_dict["rank"],
                "total_solved": doc_dict.get("total_solved"),
                "timestamp": doc_dict["timestamp"],
                "fetch_time": doc_dict.get("fetch_time")
            })
        
        # Calculate some basic analytics
        analytics = {
            "total_records": len(data),
            "best_rank": min(rank_values) if rank_values else None,
            "current_rank": rank_values[-1] if rank_values else None,
            "rank_change": rank_values[-1] - rank_values[0] if len(rank_values) > 1 else 0,
            "first_recorded": data[0]["timestamp"] if data else None,
            "last_recorded": data[-1]["timestamp"] if data else None
        }
        
        return jsonify({
            "success": True,
            "data": data,
            "analytics": analytics
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500
    

print("Registered Routes:")
for rule in app.url_map.iter_rules():
    print(rule)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

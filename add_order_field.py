from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv
import os
import certifi

# Load environment variables from .env
load_dotenv()

# Get Mongo URI from .env
mongo_uri = os.getenv("MONGO_URI")
if not mongo_uri:
    raise ValueError("❌ MONGO_URI not found in .env file")


client = MongoClient(mongo_uri, tls=True, tlsCAFile=certifi.where())
db = client.task_manager

# Loop over each user so ordering resets per user
for user in db.users.find({}):
    user_id = user["_id"]
    tasks = list(db.tasks.find({"user_id": user_id}).sort("created_at", 1))

    for index, task in enumerate(tasks, start=1):
        if "order" not in task:
            db.tasks.update_one({"_id": task["_id"]}, {"$set": {"order": index}})

print("✅ Added 'order' field to any missing tasks.")

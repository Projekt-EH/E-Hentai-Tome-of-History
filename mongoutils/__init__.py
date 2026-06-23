import pymongo
from pymongo.errors import BulkWriteError
import json
import threading
import os

def get_mongo_client():
    """
    Create and return a MongoDB client instance.
    The "mongoconfig.json" file should contain the following fields:
    {
        "host": "localhost",
        "port": 27017,
        "user": "your_username",
        "password": "your_password"
    }
    or if no authentication is needed, the "user" and "password" fields can be empty strings.
    {
        "host": "localhost",
        "port": 27017,
        "user": "",
        "password": ""
    }
    """
    mongo_config = None
    mongo_client = None
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)),"mongoconfig.json"), "r", encoding="utf-8") as f:
        mongo_config = json.load(f)
    if mongo_config["user"] == '' or mongo_config["password"] == '':
        mongo_client = pymongo.MongoClient(
            mongo_config["host"], mongo_config["port"], unicode_decode_error_handler='ignore')
    else:
        mongo_client = pymongo.MongoClient(
            f'mongodb://{mongo_config["user"]}:{mongo_config["password"]}'
            f'@{mongo_config["host"]}:{mongo_config["port"]}',
            unicode_decode_error_handler='ignore')
    print(f"Connected to MongoDB at {mongo_config['host']}:{mongo_config['port']}")
    return mongo_client


def check_database(mongo_client: pymongo.MongoClient):
    """
    Check if the required databases exist in the MongoDB server.
    If not, create them.
    """
    target_database = "ehcomment"
    required_collections = ["Comments", "comment_edits", "gallery_uploader"]

    existing_databases = mongo_client.list_database_names()
    if target_database not in existing_databases:
        print(f"Database '{target_database}' does not exist. Creating it...")
        mongo_client[target_database]  # This will create the database when a collection is created

    ehcomment_db = mongo_client[target_database]

    comment_edit_db = ehcomment_db["comment_edits"]
    # check if the index exists, if not create it

    comment_edit_db.create_index([("comment_id", pymongo.ASCENDING), ("edit_time", pymongo.ASCENDING)], unique=True, name="id_time")

    gallery_uploader_db = ehcomment_db["gallery_uploader"]
    # check if the index exists, if not create it
    gallery_uploader_db.create_index([("gallery_id", pymongo.ASCENDING), ("comment_sha256", pymongo.ASCENDING)], unique=True, name="gid_comment_hash")


class DataBuffer:
    """
    Thread-safe in-memory buffer for crawler output.

    Data is accumulated in three arrays (comments, comment edits, gallery uploaders).
    When any array reaches ``batch_size`` items, that array is flushed to MongoDB
    using bulk upserts. Callers should invoke ``flush()`` when a task completes
    to persist any remaining data.
    """

    def __init__(self, mongo_client: pymongo.MongoClient, batch_size: int = 5000):
        self.batch_size = batch_size
        db = mongo_client["ehcomment"]
        self.comments_col = db["Comments"]
        self.edits_col = db["comment_edits"]
        self.uploaders_col = db["gallery_uploader"]

        self._comments = []
        self._edits = []
        self._uploaders = []
        self._lock = threading.Lock()
        self._stats = {
            "comments": {"success": 0, "duplicate":0, "failed": 0},
            "edits": {"success": 0, "duplicate":0, "failed": 0},
            "uploaders": {"success": 0, "duplicate":0, "failed": 0},
        }

    def add_comments(self, comments: list):
        """Add a list of comment documents to the buffer and flush if needed."""
        if not comments:
            return
        with self._lock:
            self._comments.extend(comments)
            if len(self._comments) >= self.batch_size:
                self._flush_comments()

    def add_edits(self, edits: list):
        """Add a list of edit documents to the buffer and flush if needed."""
        if not edits:
            return
        with self._lock:
            self._edits.extend(edits)
            if len(self._edits) >= self.batch_size:
                self._flush_edits()

    def add_uploaders(self, uploaders: list):
        """Add a list of uploader documents to the buffer and flush if needed."""
        if not uploaders:
            return
        with self._lock:
            self._uploaders.extend(uploaders)
            if len(self._uploaders) >= self.batch_size:
                self._flush_uploaders()

    def add_gallery_result(self, comments: list, edits: list, uploaders: list):
        """
        Convenience method to add all data produced by crawling a single gallery.
        Arrays are flushed individually when they exceed the batch size.
        """
        self.add_comments(comments or [])
        self.add_edits(edits or [])
        self.add_uploaders(uploaders or [])

    def flush(self):
        """Flush all buffered arrays to MongoDB."""
        with self._lock:
            self._flush_comments()
            self._flush_edits()
            self._flush_uploaders()

    def get_stats(self):
        """Return a snapshot of write success/failure counts."""
        with self._lock:
            return {
                key: dict(value)
                for key, value in self._stats.items()
            }

    def _flush_comments(self):
        if not self._comments:
            return
        count = len(self._comments)
        operations = [
            pymongo.UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
            for doc in self._comments
        ]
        try:
            result = self.comments_col.bulk_write(operations, ordered=False)
            success = result.matched_count + result.upserted_count
            self._stats["comments"]["success"] += success
            print(f"Flushed {success}/{count} comments to MongoDB.")
        except BulkWriteError as e:
            details = e.details
            dupe_count=sum(1 for error in details.get("writeErrors", []) if error.get("code") == 11000)
            other_failures = len(details.get("writeErrors", [])) - dupe_count + len(details.get("writeConcernErrors", []))

            success = details.get("nMatched", 0) + details.get("nUpserted", 0)
            
            self._stats["comments"]["success"] += success
            self._stats["comments"]["duplicate"] += dupe_count
            self._stats["comments"]["failed"] += other_failures
            print(f"Flushed {success}/{count} comments to MongoDB.\n{dupe_count} duplicate documents skipped. {other_failures} failed to write.")
        finally:
            self._comments = []

    # use insert
    def _flush_edits(self):
        if not self._edits:
            return
        count = len(self._edits)
        try:
            result = self.edits_col.insert_many(self._edits, ordered=False)
            success = len(result.inserted_ids)
            self._stats["edits"]["success"] += success
            print(f"Flushed {success}/{count} comment edits to MongoDB.")
        except BulkWriteError as e:
            details = e.details
            dupe_count=sum(1 for error in details.get("writeErrors", []) if error.get("code") == 11000)
            other_failures = len(details.get("writeErrors", [])) - dupe_count + len(details.get("writeConcernErrors", []))
            success = details.get("nInserted", 0)
            
            self._stats["edits"]["success"] += success
            self._stats["edits"]["duplicate"] += dupe_count
            self._stats["edits"]["failed"] += other_failures
            print(f"Flushed {success}/{count} comment edits to MongoDB.\n {dupe_count} duplicate documents skipped.\n{other_failures} failed to write.")

            # print(f"Bulk write error details: {details}")
        finally:
            self._edits = []

    def _flush_uploaders(self):
        if not self._uploaders:
            return
        count = len(self._uploaders)
        try:
            result = self.uploaders_col.insert_many(self._uploaders, ordered=False)
            success = len(result.inserted_ids)
            self._stats["uploaders"]["success"] += success
            print(f"Flushed {success}/{count} gallery uploader info to MongoDB.")
        except BulkWriteError as e:
            details = e.details
            dupe_count=sum(1 for error in details.get("writeErrors", []) if error.get("code") == 11000)
            other_failures = len(details.get("writeErrors", [])) - dupe_count + len(details.get("writeConcernErrors", []))
            success = details.get("nInserted", 0)
            
            self._stats["uploaders"]["success"] += success
            self._stats["uploaders"]["duplicate"] += dupe_count
            self._stats["uploaders"]["failed"] += other_failures
            print(f"Flushed {success}/{count} gallery uploader info to MongoDB. {dupe_count} duplicate documents skipped. {other_failures} failed to write.")
            # print(f"Bulk write error details: {details}")
        finally:
            self._uploaders = []

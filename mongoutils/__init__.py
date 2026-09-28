# E-Hentai Tome of History - a gallery comment fetcher and preserver for E-Hentai
# Copyright (C) 2026  Projekt-EH & AXIS5(AXIS5hacker)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

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


def _not_flagged_filter(**extra):
    """
    Build a query filter for comments that are not flagged as deleted yet.

    MongoDB's ``$ne`` also matches documents where the field is missing or null, so comments
    written before the ``cleaned`` flag existed (older versions of this crawler) are matched
    as well and take part in the deletion comparison like any other comment.
    """
    return {"cleaned": {"$ne": True}, **extra}


class CommentDeletionTracker:
    """
    Detect comments that are gone from a gallery.

    MongoDB is the reference for "what we already had": the comment IDs of a gallery are
    snapshotted *before* that gallery is crawled, and every snapshotted ID that is missing
    from a successful crawl is flagged as deleted (``cleaned = True``). On E-Hentai a comment
    ID is stable for the lifetime of the comment (the page renders ``<a name="c8506504">`` /
    ``id="comment_8506504"``), so comparing IDs across crawls is safe and is not affected by
    other comments being added or removed.

    Comments that are already flagged (``cleaned = True``) are left out of the snapshot
    entirely: they are already known to be gone, so there is nothing to compare or to flag.
    Comments stored before the flag existed (no ``cleaned`` field at all, or a null one) are
    matched by the snapshot query and are compared like any other comment.

    A crawl that failed (request error, missing comment container, gallery removed, ...) must
    never be reported through :meth:`check` -- "not crawled" is not "deleted". For the same
    reason :meth:`check` only compares against a snapshot that was taken before the crawl:
    a gallery without a snapshot is reported as skipped instead of being compared against a
    database state that may already contain the comments of this very crawl.

    Instances are thread-safe. Batch crawling snapshots every gallery of the list up front
    with :meth:`prefetch` and then reports per gallery from the worker threads.
    """

    def __init__(self, mongo_client: pymongo.MongoClient, batch_size: int = 500, mark_deleted: bool = True):
        self.comments_col = mongo_client["ehcomment"]["Comments"]
        self.batch_size = batch_size
        self.mark_deleted = mark_deleted
        self._snapshots = {}
        self._lock = threading.Lock()
        self._stats = {
            "galleries_snapshotted": 0,
            "galleries_checked": 0,
            "galleries_skipped": 0,
            "comments_checked": 0,
            "comments_missing": 0,
            "comments_marked_deleted": 0,
            "snapshot_queries": 0,
        }

    def prefetch(self, gallery_ids):
        """
        Snapshot the existing comment IDs of many galleries in one pass.

        Used by batch crawling right after the gallery list has been collected, so that
        every comparison of the run is made against the same database state. Comments that
        are already flagged as deleted are skipped, and gallery IDs without any remaining
        comment are remembered as empty snapshots. Returns the number of unique gallery IDs
        that were snapshotted.
        """
        unique_ids = [gallery_id for gallery_id in dict.fromkeys(gallery_ids) if gallery_id]
        if not unique_ids:
            return 0

        loaded = {}
        queries = 0
        for start in range(0, len(unique_ids), self.batch_size):
            chunk = unique_ids[start:start + self.batch_size]
            queries += 1
            cursor = self.comments_col.find(
                _not_flagged_filter(gallery_id={"$in": chunk}),
                {"_id": 1, "gallery_id": 1}
            )
            for doc in cursor:
                loaded.setdefault(doc.get("gallery_id"), set()).add(doc["_id"])

        with self._lock:
            for gallery_id in unique_ids:
                # setdefault: a snapshot that already exists (just-in-time query) wins.
                self._snapshots.setdefault(gallery_id, loaded.get(gallery_id, set()))
            self._stats["galleries_snapshotted"] += len(unique_ids)
            self._stats["snapshot_queries"] += queries
        return len(unique_ids)

    def snapshot_for(self, gallery_id: str):
        """
        Return the snapshot of one gallery, either the one taken earlier (``prefetch`` or a
        previous call) or a fresh query. Comments that are already flagged as deleted are not
        part of the snapshot. Returns None for an empty gallery ID.
        """
        if not gallery_id:
            return None

        with self._lock:
            if gallery_id in self._snapshots:
                return set(self._snapshots[gallery_id])

        comment_ids = {
            doc["_id"]
            for doc in self.comments_col.find(
                _not_flagged_filter(gallery_id=gallery_id),
                {"_id": 1}
            )
        }
        with self._lock:
            self._stats["galleries_snapshotted"] += 1
            self._stats["snapshot_queries"] += 1
            return set(self._snapshots.setdefault(gallery_id, comment_ids))

    def check(self, gallery_id: str, crawled_ids, mark: bool = None):
        """
        Compare the snapshot of one gallery with the comment IDs of a successful crawl and
        flag the missing ones as deleted.

        Returns a report dict::

            {
                "gallery_id": str,
                "status": "checked" | "skipped",
                "checked": int,   # comments known from MongoDB before the crawl
                "crawled": int,   # comments returned by this crawl
                "deleted": int,   # comments present in MongoDB but not crawled
                "marked": int     # documents flagged with cleaned = True by this check
            }

        ``status`` is "skipped" when the gallery has no snapshot yet, which means the caller
        did not snapshot before crawling; nothing is marked in that case.
        """
        with self._lock:
            snapshot = self._snapshots.get(gallery_id)
            snapshot = set(snapshot) if snapshot is not None else None

        if snapshot is None:
            with self._lock:
                self._stats["galleries_skipped"] += 1
            return {
                "gallery_id": gallery_id,
                "status": "skipped",
                "checked": 0,
                "crawled": len(set(crawled_ids)),
                "deleted": 0,
                "marked": 0,
            }

        crawled = set(crawled_ids)
        missing = snapshot - crawled
        report = {
            "gallery_id": gallery_id,
            "status": "checked",
            "checked": len(snapshot),
            "crawled": len(crawled),
            "deleted": len(missing),
            "marked": 0,
        }

        should_mark = self.mark_deleted if mark is None else mark
        if missing and should_mark:
            result = self.comments_col.update_many(
                {"_id": {"$in": list(missing)}},
                {"$set": {"cleaned": True}}
            )
            report["marked"] = result.modified_count

        with self._lock:
            self._stats["galleries_checked"] += 1
            self._stats["comments_checked"] += report["checked"]
            self._stats["comments_missing"] += report["deleted"]
            self._stats["comments_marked_deleted"] += report["marked"]

        return report

    def get_stats(self):
        """Return a snapshot of the tracking counters."""
        with self._lock:
            return dict(self._stats)


def move_gallery_comments(mongo_client: pymongo.MongoClient, old_gallery_id: str, new_gallery_id: str, new_source_url: str):
    """
    Re-point the stored comments of a superseded gallery at its newest version.

    E-Hentai keeps the comment IDs when a gallery is replaced by a newer upload, so the comments
    already stored under the gallery ID of the outdated upload belong to the newest version:
    every document of ``old_gallery_id`` gets ``gallery_id`` = ``new_gallery_id`` and
    ``source_url`` = ``new_source_url`` (the URL the newest version is crawled from). The
    ``cleaned`` flag of a document is left untouched.

    Returns the number of documents that were moved (0 when the gallery IDs are equal, are
    empty, or nothing is stored for the old gallery).

    The deletion check has to snapshot the newest gallery *after* this move, which is what
    :func:`utils.crawl.crawl_comments` does: the move happens as soon as the newest version has
    been fetched, before the comment IDs of that gallery are collected.
    """
    if not old_gallery_id or not new_gallery_id or old_gallery_id == new_gallery_id:
        return 0
    result = mongo_client["ehcomment"]["Comments"].update_many(
        {"gallery_id": old_gallery_id},
        {"$set": {"gallery_id": new_gallery_id, "source_url": new_source_url}}
    )
    return result.modified_count


def get_comment_deletion_tracker(mongo_client: pymongo.MongoClient):
    """
    Create a :class:`CommentDeletionTracker`, or return None when comment deletion
    detection is switched off (``utils.constants.DELETION_DETECTION_ENABLED``) or when no
    MongoDB client is available.
    """
    if mongo_client is None:
        return None
    try:
        # Imported lazily so this storage module does not hard-depend on the crawler config.
        from utils.constants import DELETION_DETECTION_ENABLED
    except ImportError:
        DELETION_DETECTION_ENABLED = True
    if not DELETION_DETECTION_ENABLED:
        return None
    return CommentDeletionTracker(mongo_client)


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

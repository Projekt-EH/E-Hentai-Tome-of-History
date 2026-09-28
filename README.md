# E-Hentai Tome of History (Comment Crawler)

## What this is

ehcomment_crawler crawls and archives the comments of E-Hentai / ExHentai galleries into
MongoDB, keeping the **comment contents and their edit records** as historical evidence: even
after a comment is deleted, edited over and over, or its gallery is replaced, you can still
look up how it looked at every point in time. Hence the name **"Tome of History"**.

What is archived:

* every comment's content, author, score and votes (`Comments`);
* for edited comments, a snapshot of the comment at each edit timestamp, so repeated edits
  accumulate into a full edit history (`comment_edits`);
* every version of a gallery's uploader comment seen at crawl time (`gallery_uploader`);
* the fact that a comment disappeared from the page (`cleaned` flag, see "Comment deletion
  detection");
* when a gallery is replaced by a newer upload, its comments are re-pointed at the new version
  (see "Newer gallery versions").

Everything is stored in MongoDB. There are four run modes: a list of gallery URLs, batch
crawling from an uploader/listing URL, merging previously saved JSON files, and scheduled auto
jobs (see below).

## Database

The MongoDB connection is configured in `mongoconfig.json`:

```json
{
  "host": "localhost",
  "port": 27017,
  "user": "",
  "password": ""
}
```

An empty `user` / `password` means no authentication. The database is called `ehcomment` and
holds three collections; `mongoutils.check_database()` creates the database and the unique
indexes below on startup.

### Comments — the comment archive

One document per comment. `_id` is the E-Hentai comment ID (a numeric string), which stays
stable across gallery updates and therefore makes a good primary key.

| field | meaning |
| --- | --- |
| `_id` | comment ID |
| `gallery_id` | gallery ID (the newest version's ID after newer-version following) |
| `username` | commenter name (`Unknown` when it cannot be parsed) |
| `user_id`, `user_forums_url` | forum user ID and profile link (written only when the page has a `showuser=` link) |
| `post_time` | posting time (UTC `Date`; `null` when it cannot be parsed) |
| `source_url` | URL the comment was crawled from |
| `current_score` | current comment score |
| `power` | Base score |
| `vote_list` | vote details `[{ voter, power }]` ("and N more" aggregate votes are not recorded) |
| `is_edited` | whether the comment has been edited |
| `content` | comment HTML. Written only for unedited comments; the text of edited comments lives in `comment_edits.edit_content`. Writes are `$set` updates, so the pre-edit text captured by an earlier crawl stays in this field once the comment gets edited |
| `fetch_time` | time of this crawl (UTC) |
| `cleaned` | `true` means the comment is gone from the page (deleted/removed); rows written by older crawler versions have no such field and count as alive |

### comment_edits — the edit records

One document per observed "edited state" of a comment. Insert-only (never updated). The unique
index `(comment_id, edit_time)` (index name `id_time`) makes re-crawls of the same edit
timestamp duplicates that are skipped.

| field | meaning |
| --- | --- |
| `comment_id` | matches `Comments._id` |
| `edit_time` | the edit timestamp shown on the page ("Last edited on …", UTC `Date`) |
| `edit_content` | the comment HTML at that edit timestamp |

Every further edit of a comment is written as a new record with the new `edit_time`; older
records stay untouched. Sorting a comment's `edit_content` records by `edit_time` therefore
gives its full edit history.

### gallery_uploader — uploader info

One document per crawled gallery. Insert-only. The unique index `(gallery_id, comment_sha256)`
(index name `gid_comment_hash`) deduplicates: a re-crawl with an unchanged uploader comment
does not add a row.

| field | meaning |
| --- | --- |
| `gallery_id`, `source_url`, `time` | gallery ID, crawl source URL, crawl time |
| `uploader_name`, `uploader_id` | uploader name and forum ID (from `#gdn`) |
| `uploader_comment` | the uploader comment (c0) HTML |
| `comment_sha256` | SHA-256 of `uploader_comment`, used for the deduplication above |

Several rows for the same `gallery_id` mean the uploader comment changed between crawls; see
"Edited uploader comments" below to query those histories.

## Querying comments and their edit history

### Single gallery / single comment

```js
use ehcomment

// all comments of one gallery (_id is the comment ID)
db.Comments.find({ gallery_id: "90001" })

// all edit records of one comment, oldest first
db.comment_edits.find({ comment_id: "8506504" }).sort({ edit_time: 1 })

// comments that were deleted
db.Comments.find({ cleaned: true })
```

### Full edit-history aggregate (mongodb_query_commentAggregate.txt)

`mongodb_query_commentAggregate.txt` contains a ready-made aggregation that joins `Comments`
with `comment_edits` and returns the complete edit history of every edited comment in one
query. Paste it into a mongosh session (running the file through `mongosh --file` does not
print the cursor result; paste it interactively or append `.toArray()`):

```shell
mongosh "mongodb://localhost:27017/ehcomment"
```

The pipeline stages are:

1. `$match: { is_edited: true }` — only comments that have been edited;
2. `$lookup` into `comment_edits`, grouping all edit records of the comment into an `edit`
   array;
3. `$unwind`, then `$project` into the final shape: `_id` (comment ID), `gallery_id`,
   `username`, `post_time`, `content`, `edit` (`[{ edit_time, edit_content }]`), `vote_list`,
   `current_score`, `power`;
4. a final `$match` that keeps only documents whose `content` is not null or whose `edit`
   array holds more than one entry — i.e. comments that really left a trace of change (the
   pre-edit text is still stored, or several edit versions were recorded).

In the result, `content` is the pre-edit text of the comment (present only if it was crawled
while still unedited) and `edit` is the snapshot taken at each edit timestamp; together they
are the comment's "tome of history". To see every edited comment (including single-edit ones
without stored pre-edit text), drop the last `$match` stage.

### Edited uploader comments (mongodb_query_editedUploaderComment.txt)

`mongodb_query_editedUploaderComment.txt` is the matching aggregation for the uploader comment
(c0). `gallery_uploader` stores one row per observed uploader-comment state — the unique index
`gallery_id + comment_sha256` skips re-crawls whose comment is unchanged — so the query only
has to group the rows of a gallery and keep the galleries whose uploader comment was seen in
more than one version. Paste it into mongosh the same way as above.

The pipeline stages are:

1. `$group` by `gallery_id` + `source_url`, pushing every observed `uploader_comment` into an
   `edits` array;
2. `$match` keeps only groups with more than one entry, i.e. galleries whose uploader comment
   changed between crawls.

The result is `_id: { gallery_id, url }` plus `edits: [{ uploader_comment }, …]`: the versions
of the uploader comment in stored order. The output is not timestamped; each row also carries
`time` (its crawl time), which can be pushed alongside `uploader_comment` when the chronology
of the versions is needed.

## Run

```shell
python __init__.py
```

or

```shell
python __init__.py -p <parallel_workers>
```

The argument "parallel_workers" sets the number of parallel threads in
uploader/listing URL crawling.

The maximum number allowed is 20.

## Interactive mode

Mode 1 reads gallery URLs from the terminal, one URL per line; an empty line starts the
crawling, and duplicate lines are skipped. The whole list is crawled with one data buffer and
one comment-deletion snapshot taken before the first request (see "Comment deletion
detection"), and one report is printed per URL.
Mode 2 crawls every gallery found on an uploader/listing URL, mode 3 merges previously saved
JSON files and mode 4 runs the jobs of `auto_jobs.json`.

## Config

The config file looks like this:

```json
{
  "igneous": "mystery",
  "ipb_member_id": "0",
  "ipb_pass_hash": "0",
  "nw":"1",
  "hath_perks":"",
  "star":""
}
```

You can modify it to match with your settings.

## Auto jobs (`auto_jobs.json`)

Mode 4 of the interactive entry, or `python __init__.py --auto [path]`, runs the jobs of a JSON
config in a loop. Without a path, `auto_jobs.json` in the project root is used; both the
interactive prompt and `--auto <path>` accept a different file. `-p <parallel_workers>` sets
the worker threads used by `uploader` jobs.

Top-level fields:

| field | meaning |
| --- | --- |
| `interval_minutes` | pause between two rounds, in minutes (positive number, default 60) |
| `interval_jitter` | relative jitter of that pause (non-negative number, default 0.10); the actual sleep is drawn uniformly from `interval_minutes × (1 ± interval_jitter)` |
| `start_at`, `end_at` | optional local-time bounds, format `YYYY-MM-DD HH:MM`. Auto mode waits before `start_at` and exits at `end_at` (also in the middle of a wait). Omit or leave empty for no bounds |
| `jobs` | array of job objects, executed in the given order |

Each job object:

| field | meaning |
| --- | --- |
| `enabled` | `false` skips the job (default `true`) |
| `type` | `"gallery"` or `"uploader"` |

A `gallery` job takes `urls`: one gallery URL, or an array of them (duplicates are skipped; the
singular `url` is rejected for gallery jobs). Its URLs are crawled exactly like interactive
mode 1, with one shared data buffer and one deletion-detection snapshot for the whole list.

An `uploader` job takes `url` (one uploader/listing URL, required) and an optional
`page_depth`: empty or missing = automatic, `0` = first page only, `N` = follow the "next"
link `N` times (a number or a numeric string).

Each round runs every enabled job in order (a failing job is reported and the run continues
with the next one), then sleeps `interval_minutes ± jitter` and starts the next round. The
config file is re-read at the start of every round, so edits — disabling a job, changing the
interval — take effect without a restart; only a missing/invalid config file or a wrongly
formatted `start_at`/`end_at` aborts the run. Stop auto mode with Ctrl+C.

Example:

```json
{
  "interval_minutes": 65,
  "interval_jitter": 0.20,
  "start_at": "2026-06-21 08:00",
  "end_at": "2027-09-28 23:00",
  "jobs": [
    {
      "enabled": true,
      "type": "uploader",
      "url": "https://e-hentai.org/?f_search=...",
      "page_depth": "1"
    },
    {
      "enabled": true,
      "type": "gallery",
      "urls": ["https://e-hentai.org/g/1234567/abcdef12/"]
    }
  ]
}
```

## Newer gallery versions

E-Hentai shows a "There are newer versions of this gallery available:" notice inside
`<div id="gnd">` when a gallery has been replaced by a newer upload. The crawler detects that
notice and follows it: the bottom-most link of the notice (the newest version) is crawled
instead of the requested URL, and the comments are stored under the gallery ID of the newest
version. Each switch is announced with `switched to new version: <gallery ID>` right before
that version is requested. The chain is followed until a page without the notice is reached, a
version repeats, or `MAX_GALLERY_VERSION_HOPS` (5) hops were made.

### Gallery update

E-Hentai keeps the comment IDs when a gallery is replaced, so the comments already stored for
the outdated gallery belong to the newest version. As soon as the newest version has been
fetched, every comment stored under the gallery ID of the outdated upload is re-pointed at the
newest version: `gallery_id` becomes the new gallery ID and `source_url` becomes the URL the
newest version is crawled from (`Gallery update: <n> comment(s) moved from <old> to <new>` is
printed when something moved). The `cleaned` flag of those comments is left as it is (a comment
that was already flagged as deleted keeps its flag and stays out of the existence check). The
move happens before the comment IDs of the newest gallery are collected, so a comment of the
old gallery that is missing from the newest version's page is flagged as deleted by the same
crawl.

A switch is only applied when the newest version could actually be fetched: if the request for
it fails, the comments stay under the old gallery. Rows of the `gallery_uploader` collection are
not re-pointed, only the comments themselves.

## Comment deletion detection

Before a gallery is crawled, the comment IDs already stored in MongoDB for that gallery are
collected; after a successful crawl the two sets are compared and every stored comment that
was not seen again is treated as deleted and flagged in the database with `cleaned: true`.
Comments that are already flagged are ignored (they are known to be gone, so they are not
collected again). A comment that is crawled again is written back as `cleaned: false`.

Comparisons use the comment ID (`_id`), which is stable on E-Hentai. Comments stored by older
versions of this crawler have no `cleaned` field at all; they are treated as existing comments
and therefore take part in the comparison like any other (the MongoDB filter is
`cleaned != true`, which also matches documents without the field). Once a comment is crawled
again or flagged, the field is written from then on.

Notes:

* Single gallery crawl: the snapshot is taken for the crawled gallery before its page is
  parsed, so the comments of the running crawl can not hide a deletion.
* Batch crawl (`crawl_uploader_galleries`) and auto-mode gallery jobs: the snapshot of every
  gallery of the list is taken up front, in one pass, before the first request; each gallery is
  then compared right after its own successful crawl.
* A crawl that failed (request error, missing comment container, gallery removed/expunged,
  permission denied, ...) is never compared, so an unavailable gallery does not mark its
  comments as deleted.
* The check can be switched off with `DELETION_DETECTION_ENABLED` in `utils/constants.py`.

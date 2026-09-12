# E-Hentai Comment Crawler

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

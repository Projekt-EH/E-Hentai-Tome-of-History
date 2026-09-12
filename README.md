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

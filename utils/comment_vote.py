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

"""Downvote E-Hentai gallery comments through the site's own votecomment API.

The gallery page passes the vote credentials to its inline scripts as the globals
``api_url``, ``apiuid``, ``apikey``, ``gid`` and ``token``.  The site's ``vote_comment()``
(see ``ehg_gallery.c.js``) posts them to the API as JSON:

    POST {api_url}
    Content-Type: application/json
    {"method": "votecomment", "apiuid": ..., "apikey": ..., "gid": ...,
     "token": ..., "comment_id": ..., "comment_vote": -1}

and applies the response's ``comment_score`` / ``comment_vote`` to the page.  This module
sends the same request through the crawler's cookie session, one comment at a time, with
``VOTE_INTERVAL_SECONDS`` between the comments of a list.
"""

import random
import re
import time

from urllib.parse import urlparse

import requests

from .urlfetch import SESSION, extract_gallery_key, process_url, request_html

COMMENT_VOTE_UP = 1
COMMENT_VOTE_DOWN = -1

# The site refuses every comment vote in a gallery where the logged-in user has posted a
# comment (EHWiki: "Cannot vote when own comment exists in gallery").  All further votes in
# that gallery would fail the same way, so the gallery is skipped after the first rejection.
_GALLERY_BLOCKED_ERROR = "own comment exists in gallery"

# Client-side pacing, not a documented server rate limit: sample a fresh delay per request.
VOTE_INTERVAL_SECONDS = 1.5
VOTE_INTERVAL_JITTER_SECONDS = 0.3

# The gallery page script defines the credentials the page's JavaScript uses, e.g.
#     var api_url = "https://e-hentai.org/api.php";
#     var apiuid = 123456;
#     var apikey = "0123456789abcdef0123456789abcdef";
#     var gid = 1234567;
#     var token = "0123456789";
_GALLERY_VARIABLE_PATTERNS = {
    "api_url": r"""(?:var|let|const)\s+api_url\s*=\s*["']([^"']+)["']""",
    "apiuid": r"""(?:var|let|const)\s+apiuid\s*=\s*(\d+)""",
    "apikey": r"""(?:var|let|const)\s+apikey\s*=\s*["']([^"']+)["']""",
    "gid": r"""(?:var|let|const)\s+gid\s*=\s*(\d+)""",
    "token": r"""(?:var|let|const)\s+token\s*=\s*["']([^"']+)["']""",
}

_COMMENT_ID_PATTERNS = (
    re.compile(r"^(\d+)$"),
    re.compile(r"#c(\d+)"),
    re.compile(r"[?&]c=(\d+)"),
)

# Comment anchors rendered by the gallery page: <a name="c8506504"> (c0 is the uploader
# comment and is not a votable comment).
_COMMENT_ANCHOR_PATTERN = re.compile(
    r"""<a\b[^>]*\bname\s*=\s*["']c(\d+)["']""",
    re.IGNORECASE,
)

# The page marks the votes the logged-in user has already cast with a non-empty style on the
# vote link, e.g. <a id="comment_vote_down_8506504" style="color:blue" ...>Vote-</a>, while an
# unused vote link renders with style="".  Sending comment_vote = -1 again for a comment that
# is already downvoted makes the site *withdraw* the vote, so these links are the only way to
# tell the two cases apart before calling the API.
_VOTE_DOWN_LINK_PATTERN = re.compile(
    r"""<a\b([^>]*\bid\s*=\s*["']comment_vote_down_(\d+)["'][^>]*)>""",
    re.IGNORECASE,
)
_STYLE_ATTRIBUTE_PATTERN = re.compile(
    r"""\bstyle\s*=\s*(["'])(?P<value>.*?)\1""",
    re.IGNORECASE | re.DOTALL,
)

# Vote links the page renders for every comment the logged-in user may vote on:
# <a id="comment_vote_up_8506504" ...>Vote+</a> / <a id="comment_vote_down_8506504" ...>Vote-</a>.
# When the user has posted a comment in the gallery, E-Hentai removes both links from every
# comment, so a page that renders user comments but not a single vote link means voting is
# disabled for that gallery.
_VOTE_LINK_PATTERN = re.compile(
    r"""\bid\s*=\s*["']comment_vote_(?:up|down)_(\d+)["']""",
    re.IGNORECASE,
)


def extract_comment_ids(html: str):
    """
    Return the comment IDs anchored in a gallery page (``name="c<ID>"``), excluding the
    uploader comment (``c0``).
    """
    return {
        match.group(1)
        for match in _COMMENT_ANCHOR_PATTERN.finditer(html)
        if match.group(1) != "0"
    }


def extract_downvoted_comment_ids(html: str):
    """
    Return the IDs of the comments the logged-in user has already downvoted on this page.

    The gallery page renders a link per votable comment, ``id="comment_vote_down_<ID>"``, and
    gives it a non-empty ``style`` attribute when the user's current vote is a downvote.  A
    link without a style (or with ``style=""``) means no downvote has been cast.
    """
    downvoted = set()
    for match in _VOTE_DOWN_LINK_PATTERN.finditer(html):
        style = _STYLE_ATTRIBUTE_PATTERN.search(match.group(1))
        if style and style.group("value").strip():
            downvoted.add(match.group(2))
    return downvoted


def extract_vote_link_ids(html: str):
    """Return the comment IDs that carry a Vote+ or Vote- link on the page."""
    return {match.group(1) for match in _VOTE_LINK_PATTERN.finditer(html)}


def _page_comment_state(html: str):
    """
    Parse ``(comment_ids, downvoted_ids, voting_disabled)`` from a gallery page.

    ``voting_disabled`` is True when the page renders user comments but not a single
    Vote+/Vote- link.  E-Hentai removes those links from every comment when the logged-in
    user has posted a comment in the gallery, so this identifies the condition without
    sending a vote.  A page without user comments (only the uploader comment) is not
    treated as disabled.
    """
    comment_ids = extract_comment_ids(html)
    downvoted_ids = extract_downvoted_comment_ids(html)
    voting_disabled = bool(comment_ids) and not extract_vote_link_ids(html)
    return comment_ids, downvoted_ids, voting_disabled


def _load_gallery_page(gallery_url: str, session=None):
    """
    Request a gallery page and return ``(context, target_url, html)``.

    Returns ``(None, None, None)`` when the URL is invalid, the page can not be fetched, or
    the page carries no vote credentials (expired session / not logged in).
    """
    session = session or SESSION

    target_url, gallery_id = process_url(gallery_url)
    if not target_url:
        return None, None, None

    result = request_html(target_url, session)
    if not result["ok"]:
        print(f"Could not load gallery page: {result['error']}")
        return None, None, None

    context = parse_gallery_api_context(result["html"])
    if context is None:
        print(
            "Could not read the gallery's vote credentials (apiuid/apikey/gid/token). "
            "The session is probably not logged in; check config.json."
        )
        return None, None, None

    if str(context["gid"]) != str(gallery_id):
        print(
            f"Warning: the gallery page reports gid {context['gid']} but the URL "
            f"contains gallery ID {gallery_id}."
        )

    return context, target_url, result["html"]


def fetch_gallery_vote_state(gallery_url: str, session=None):
    """
    Request a gallery page and return ``(context, target_url, downvoted_ids, voting_disabled)``.

    ``downvoted_ids`` holds the comments the logged-in user has already downvoted; sending
    another downvote for one of them would withdraw the existing vote.  ``voting_disabled``
    is True when the page renders comments but no Vote+/Vote- links at all (the user has
    posted a comment in this gallery).  On failure the first two values are None and the
    sets/flag are empty/False.
    """
    context, target_url, html = _load_gallery_page(gallery_url, session)
    if context is None:
        return None, None, set(), False
    _, downvoted_ids, voting_disabled = _page_comment_state(html)
    return context, target_url, downvoted_ids, voting_disabled


def fetch_gallery_context_and_comments(gallery_url: str, session=None):
    """
    Request a gallery page and return
    ``(context, target_url, comment_ids, downvoted_ids, voting_disabled)``.

    ``comment_ids`` is the set of comment IDs anchored on that page; it lets the caller
    decide which gallery a comment ID belongs to without a database round trip.
    ``downvoted_ids`` is the subset the logged-in user has already downvoted, and
    ``voting_disabled`` is True when the page has comments but no vote links at all.  On
    failure the sets are empty, the flag is False, and the first two values are None.
    """
    context, target_url, html = _load_gallery_page(gallery_url, session)
    if context is None:
        return None, None, set(), set(), False
    comment_ids, downvoted_ids, voting_disabled = _page_comment_state(html)
    return context, target_url, comment_ids, downvoted_ids, voting_disabled


def parse_gallery_api_context(html: str):
    """
    Extract the vote credentials from a gallery page.

    Returns a dict with int ``apiuid`` / ``gid`` and str ``api_url`` / ``apikey`` /
    ``token``, or None when the page does not contain them (normally because the request
    was not authenticated and E-Hentai served the login page instead).
    """
    context = {}
    for name, pattern in _GALLERY_VARIABLE_PATTERNS.items():
        match = re.search(pattern, html)
        if not match:
            return None
        context[name] = match.group(1)

    context["apiuid"] = int(context["apiuid"])
    context["gid"] = int(context["gid"])
    return context


def vote_comment(context: dict, comment_id: str, vote: int, session=None):
    """
    Send one ``votecomment`` API call and return the decoded JSON response.

    Transport and decoding failures are returned as ``{"error": "..."}`` so callers can
    report a single failed comment without aborting the rest of the list.
    """
    session = session or SESSION

    payload = {
        "method": "votecomment",
        "apiuid": context["apiuid"],
        "apikey": context["apikey"],
        "gid": context["gid"],
        "token": context["token"],
        "comment_id": int(comment_id),
        "comment_vote": vote,
    }

    try:
        response = session.post(context["api_url"], json=payload, timeout=12)
    except requests.exceptions.RequestException as exc:
        return {"error": f"request failed: {exc}"}

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}

    try:
        data = response.json()
    except ValueError:
        return {"error": f"invalid JSON response: {response.text[:200]}"}

    if not isinstance(data, dict):
        return {"error": f"unexpected API response: {data!r}"}

    return data


def _format_signed(value):
    try:
        return f"{int(value):+d}"
    except (TypeError, ValueError):
        return repr(value)


ARCHIVE_DATABASE = "ehcomment"
COMMENTS_COLLECTION = "Comments"


def resolve_comment_galleries(comment_ids, mongo_client):
    """
    Map comment IDs to the gallery page URL stored in the local comment archive.

    ``Comments._id`` is the comment ID and ``Comments.source_url`` is the gallery URL the
    comment was last crawled from, so an ID-only vote can reuse exactly the gallery page the
    crawler already knows.  Returns ``(pairs, missing)`` where ``pairs`` is
    ``[(comment_id, source_url), ...]`` in input order and ``missing`` holds the IDs that
    have no archived gallery URL.
    """
    if mongo_client is None:
        raise ValueError("A MongoDB client is required to resolve comment IDs to galleries.")

    ids = [str(comment_id) for comment_id in comment_ids]
    collection = mongo_client[ARCHIVE_DATABASE][COMMENTS_COLLECTION]
    documents = collection.find(
        {"_id": {"$in": ids}},
        {"_id": 1, "source_url": 1},
    )
    source_urls = {
        str(document["_id"]): document.get("source_url")
        for document in documents
    }

    pairs = []
    missing = []
    for comment_id in ids:
        source_url = source_urls.get(comment_id)
        if source_url:
            pairs.append((comment_id, source_url))
        else:
            missing.append(comment_id)

    return pairs, missing


def resolve_cleaned_comment_ids(comment_ids, mongo_client):
    """
    Return the comment IDs that are flagged ``cleaned = True`` in the local archive.

    ``cleaned`` is the crawler's "not rendered on the gallery page" flag.  Such comments are
    perma-hidden or gone, so they are skipped instead of being downvoted blindly (their
    current vote state cannot be read from the page).  Input order is preserved.
    """
    if mongo_client is None:
        raise ValueError("A MongoDB client is required to resolve cleaned comment IDs.")

    ids = [str(comment_id) for comment_id in comment_ids]
    if not ids:
        return []

    collection = mongo_client[ARCHIVE_DATABASE][COMMENTS_COLLECTION]
    documents = collection.find(
        {"_id": {"$in": ids}, "cleaned": True},
        {"_id": 1},
    )
    cleaned = {str(document["_id"]) for document in documents}
    return [comment_id for comment_id in ids if comment_id in cleaned]


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _gallery_page_key(gallery_url: str):
    """
    Identity used to cache a loaded gallery page.

    The user can name a gallery without ``?hc=1`` while the archive stores the crawler's
    cleaned URL for the same gallery, so both spellings must share one page load.  The host
    is part of the key (E-Hentai and ExHentai are different sites) and the gallery ID
    identifies the page; URLs that are not gallery URLs are keyed by their literal value.
    """
    gallery_key = extract_gallery_key(gallery_url)
    if gallery_key:
        return f"{urlparse(gallery_url).netloc.lower()}/g/{gallery_key[0]}"
    return gallery_url


def _vote_plan(plan, interval, session, sleep, initial_skipped=None, contexts=None):
    """
    Execute a ``[(gallery_url, comment_id), ...]`` plan, caching one API context (and the
    page's set of already-downvoted comment IDs) per gallery.  Used by all voting entry
    points; ``contexts`` may be preloaded by the caller so a page is not requested twice.
    Different spellings of the same gallery (with or without ``?hc=1``) share one cache
    entry and therefore one page load.

    A comment the page already shows as downvoted is skipped: re-sending
    ``comment_vote = -1`` would make E-Hentai withdraw the existing vote.  Skipped comments
    cost no delay; the ``interval`` is enforced between the API requests that are actually
    sent.  The API's own ``comment_vote`` reply is checked as well.  A reply of 0 means the
    server withdrew an existing downvote that the page snapshot did not show; the vote is
    re-applied once, because the server state is now 0 and cannot be toggled again.  A second
    reply that is not -1 is reported as failed instead of counted as downvoted.

    If the gallery page renders comments but no Vote+/Vote- links at all, the logged-in user
    has posted a comment in that gallery (E-Hentai removes the links from every comment), so
    the whole gallery is skipped without sending a vote.  The same gallery-level block is
    also applied if the server returns "Cannot vote when own comment exists in gallery"
    anyway (for example when the page was cached before the comment was posted).
    """
    summary = {
        "ok": False,
        "gallery_url": None,
        "galleries": [],
        "voted": [],
        "already_downvoted": [],
        "reapplied": [],
        "failed": [],
        "skipped": list(initial_skipped or []),
        "blocked_galleries": [],
        "affected_galleries": [],
    }

    if not plan:
        if summary["skipped"]:
            print("No comment was left to vote.")
            print(
                f"Done: 0 downvoted, 0 already downvoted, 0 failed, "
                f"{len(summary['skipped'])} skipped."
            )
        else:
            print("No comment ID to vote on.")
            summary["ok"] = True
        return summary

    contexts = dict(contexts or {})
    total = len(plan)
    last_request_at = None
    blocked_galleries = set()

    def send_vote(context, comment_id):
        """Space actual requests by ``interval`` ± 0.3 seconds, clamped at zero."""
        nonlocal last_request_at
        if last_request_at is not None:
            delay = random.uniform(
                max(0.0, interval - VOTE_INTERVAL_JITTER_SECONDS),
                max(0.0, interval + VOTE_INTERVAL_JITTER_SECONDS),
            ) if interval > 0 else 0.0
            remaining = delay - (time.monotonic() - last_request_at)
            if remaining > 0:
                sleep(remaining)
        data = vote_comment(context, comment_id, COMMENT_VOTE_DOWN, session)
        last_request_at = time.monotonic()
        return data

    for position, (gallery_url, comment_id) in enumerate(plan):
        page_key = _gallery_page_key(gallery_url)
        if page_key not in contexts:
            print(f"Loading gallery page: {gallery_url}")
            contexts[page_key] = fetch_gallery_vote_state(gallery_url, session)

        if page_key in blocked_galleries:
            print(
                f"[{position + 1}/{total}] comment {comment_id}: skipped "
                f"(voting is not allowed in this gallery)."
            )
            summary["skipped"].append(comment_id)
            continue

        context, target_url, downvoted_ids, voting_disabled = contexts[page_key]
        if context is not None:
            if target_url not in summary["galleries"]:
                summary["galleries"].append(target_url)
            if summary["gallery_url"] is None:
                summary["gallery_url"] = target_url

        if voting_disabled:
            blocked_galleries.add(page_key)
            if target_url not in summary["blocked_galleries"]:
                summary["blocked_galleries"].append(target_url)
            print(
                f"[{position + 1}/{total}] comment {comment_id}: skipped "
                f"(the page has no Vote+/Vote- links: you have a comment in this gallery)."
            )
            summary["skipped"].append(comment_id)
            continue

        if context is None:
            print(f"[{position + 1}/{total}] comment {comment_id}: skipped (gallery page unavailable).")
            summary["skipped"].append(comment_id)
        elif comment_id in downvoted_ids:
            print(
                f"[{position + 1}/{total}] comment {comment_id}: already downvoted; "
                f"left unchanged."
            )
            summary["already_downvoted"].append(comment_id)
        else:
            data = send_vote(context, comment_id)

            if "login" in data:
                print(f"[{position + 1}/{total}] comment {comment_id}: session expired; stopping.")
                summary["skipped"].extend(id_ for _, id_ in plan[position:])
                break

            if "error" in data and _GALLERY_BLOCKED_ERROR in str(data["error"]).lower():
                blocked_galleries.add(page_key)
                if target_url not in summary["blocked_galleries"]:
                    summary["blocked_galleries"].append(target_url)
                print(
                    f"[{position + 1}/{total}] comment {comment_id}: cannot vote: "
                    f"{data['error']}. Skipping the remaining comment(s) of this gallery."
                )
                summary["skipped"].append(comment_id)
                continue

            reapplied = False
            if "error" not in data and _as_int(data.get("comment_vote")) == 0:
                # The page did not mark this comment as downvoted, but the server turned the
                # request into a withdrawal: the account already had a downvote that the
                # snapshot could not see (the vote was cast after the page was fetched, or
                # the comment was not rendered with a vote link).  The vote is now 0, so
                # repeating -1 cannot toggle it again and restores the intended state.
                print(
                    f"[{position + 1}/{total}] comment {comment_id}: the site had a "
                    f"downvote the page did not show (not rendered); re-applying."
                )
                data = send_vote(context, comment_id)
                reapplied = True

                if "login" in data:
                    print(f"[{position + 1}/{total}] comment {comment_id}: session expired; stopping.")
                    summary["skipped"].extend(id_ for _, id_ in plan[position:])
                    break

            if "error" in data:
                print(f"[{position + 1}/{total}] comment {comment_id}: failed: {data['error']}")
                summary["failed"].append({"comment_id": comment_id, "error": data["error"]})
            else:
                reported_vote = _as_int(data.get("comment_vote"))
                if reported_vote == COMMENT_VOTE_DOWN:
                    print(
                        f"[{position + 1}/{total}] comment {comment_id}: "
                        f"score {_format_signed(data.get('comment_score'))}, downvoted"
                    )
                    summary["voted"].append(comment_id)
                    if reapplied:
                        summary["reapplied"].append(comment_id)
                    if target_url not in summary["affected_galleries"]:
                        summary["affected_galleries"].append(target_url)
                else:
                    error = f"downvote not applied (server reports vote {reported_vote!r})"
                    print(f"[{position + 1}/{total}] comment {comment_id}: {error}.")
                    summary["failed"].append({"comment_id": comment_id, "error": error})

    summary["ok"] = not summary["failed"] and not summary["skipped"]
    reapplied_note = (
        f" ({len(summary['reapplied'])} re-applied)" if summary["reapplied"] else ""
    )
    print(
        f"Done: {len(summary['voted'])} downvoted{reapplied_note}, "
        f"{len(summary['already_downvoted'])} already downvoted, "
        f"{len(summary['failed'])} failed, {len(summary['skipped'])} skipped."
    )
    return summary


def downvote_comments(
    gallery_url: str,
    comment_ids,
    interval: float = VOTE_INTERVAL_SECONDS,
    session=None,
    sleep=time.sleep,
):
    """
    Downvote the given comment(s) of one gallery, one request per comment.

    Requests are spaced by ``interval`` ± 0.3 seconds (zero disables waiting). The gallery is
    requested once; its ``apiuid`` / ``apikey`` / ``gid`` / ``token`` are reused for all
    votes.  Comments the page already shows as downvoted are left untouched instead of being
    voted again (a repeated downvote would withdraw the existing one).  A failed comment is
    reported and the batch continues; an expired session (a response with a ``login`` field)
    stops the batch because the remaining votes can not succeed.

    Returns a summary dict:
        {
            "ok": bool,                    # no comment failed or was skipped
            "gallery_url": str | None,     # first page the credentials came from
            "galleries": [str, ...],       # every page used (one for this entry point)
            "voted": [comment_id, ...],    # votes accepted (comment_vote = -1)
            "already_downvoted": [comment_id, ...],  # left unchanged
            "reapplied": [comment_id, ...],  # voted after the server withdrew a stale vote
            "failed": [{"comment_id": ..., "error": ...}, ...],
            "skipped": [comment_id, ...],  # not attempted (bad page / login expired / blocked)
            "blocked_galleries": [str, ...],  # own comment exists; no vote allowed there
            "affected_galleries": [str, ...]  # pages with at least one accepted vote
        }
    """
    comment_ids = [str(comment_id) for comment_id in comment_ids]
    plan = [(gallery_url, comment_id) for comment_id in comment_ids]
    return _vote_plan(plan, interval, session or SESSION, sleep)


def downvote_comments_by_ids(
    comment_ids,
    mongo_client,
    interval: float = VOTE_INTERVAL_SECONDS,
    session=None,
    sleep=time.sleep,
):
    """
    Downvote comments from their IDs alone.

    Each ID is resolved to a gallery URL through the local comment archive
    (``Comments._id`` -> ``Comments.source_url``, see :func:`resolve_comment_galleries`),
    then voted exactly like :func:`downvote_comments`.  Comments of several galleries are
    voted in input order with the same ``interval`` between every request; the gallery page
    of each distinct URL is fetched once.  IDs that are not in the archive (or have no
    ``source_url``) are reported and skipped.

    The archive must have been populated by the crawler before using this entry point.
    """
    comment_ids = [str(comment_id) for comment_id in comment_ids]
    if not comment_ids:
        return _vote_plan([], interval, session or SESSION, sleep)
    if mongo_client is None:
        raise ValueError("A MongoDB client is required to resolve comment IDs to galleries.")

    return downvote_comments_in_galleries(
        [],
        comment_ids,
        mongo_client=mongo_client,
        interval=interval,
        session=session,
        sleep=sleep,
    )


def downvote_comments_in_galleries(
    gallery_urls,
    comment_ids,
    mongo_client=None,
    interval: float = VOTE_INTERVAL_SECONDS,
    session=None,
    sleep=time.sleep,
):
    """
    Downvote comment IDs using a list of gallery pages as the primary gallery source.

    Every provided gallery page is requested once and the comment IDs anchored on it are
    matched against the requested IDs, so the page itself decides which gallery each vote
    belongs to.  Comments flagged ``cleaned = True`` in the local archive (perma-hidden or
    gone) are skipped before any page is requested when ``mongo_client`` is given.  IDs that
    are not found on any provided page are looked up through the local comment archive
    (``Comments._id`` -> ``Comments.source_url``) when ``mongo_client`` is given, and skipped
    otherwise. Votes follow input order, spaced by ``interval`` ± 0.3 seconds.

    The summary's ``affected_galleries`` lists the pages where at least one vote was
    accepted; this is the set a caller should re-crawl after voting.
    """
    session = session or SESSION
    if isinstance(gallery_urls, str):
        gallery_urls = [gallery_urls]
    wanted = list(dict.fromkeys(str(comment_id) for comment_id in comment_ids))

    if not wanted:
        return _vote_plan([], interval, session, sleep)

    cleaned = []
    if mongo_client is not None:
        cleaned = resolve_cleaned_comment_ids(wanted, mongo_client)
        if cleaned:
            cleaned_set = set(cleaned)
            for comment_id in cleaned:
                print(
                    f"Comment {comment_id} is flagged cleaned (perma-hidden or gone) in the "
                    f"archive; skipping."
                )
            wanted = [comment_id for comment_id in wanted if comment_id not in cleaned_set]
            if not wanted:
                return _vote_plan(
                    [], interval, session, sleep, initial_skipped=cleaned
                )

    contexts = {}
    resolved = {}

    for gallery_url in gallery_urls:
        if len(resolved) == len(wanted):
            break
        page_key = _gallery_page_key(gallery_url)
        if page_key in contexts:
            continue
        print(f"Loading gallery page: {gallery_url}")
        context, target_url, page_comment_ids, page_downvoted, page_voting_disabled = (
            fetch_gallery_context_and_comments(gallery_url, session)
        )
        contexts[page_key] = (
            context, target_url, page_downvoted, page_voting_disabled
        )
        if context is None:
            continue
        for comment_id in wanted:
            if comment_id in page_comment_ids and comment_id not in resolved:
                resolved[comment_id] = gallery_url

    missing = [comment_id for comment_id in wanted if comment_id not in resolved]
    if missing and mongo_client is not None:
        print(f"Looking up {len(missing)} unmatched comment(s) in the local comment archive...")
        pairs, _ = resolve_comment_galleries(missing, mongo_client)
        for comment_id, source_url in pairs:
            page_key = _gallery_page_key(source_url)
            if page_key not in contexts:
                print(f"Loading gallery page: {source_url}")
                context, target_url, _, page_downvoted, page_voting_disabled = (
                    fetch_gallery_context_and_comments(source_url, session)
                )
                contexts[page_key] = (
                    context, target_url, page_downvoted, page_voting_disabled
                )
            resolved[comment_id] = source_url
        missing = [comment_id for comment_id in wanted if comment_id not in resolved]

    for comment_id in missing:
        print(
            f"Comment {comment_id} was not found in the provided galleries or the local "
            f"archive; skipping."
        )

    plan = [(resolved[comment_id], comment_id) for comment_id in wanted if comment_id in resolved]
    return _vote_plan(
        plan,
        interval,
        session,
        sleep,
        initial_skipped=cleaned + missing,
        contexts=contexts,
    )


def parse_comment_id(value: str):
    """
    Return the comment ID carried by a plain ID ("8506504") or a comment permalink
    (".../#c8506504", "...?c=8506504"), or None when no ID can be found.
    """
    text = str(value).strip()
    for pattern in _COMMENT_ID_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def normalize_comment_ids(values):
    """
    Turn raw input tokens into unique comment IDs, keeping the input order.

    Returns ``(comment_ids, invalid_values)``: duplicates are reported and skipped, and
    tokens without a recognizable comment ID are returned in ``invalid_values``.
    """
    comment_ids = []
    invalid_values = []
    seen = set()

    for value in values:
        comment_id = parse_comment_id(value)
        if comment_id is None:
            invalid_values.append(str(value))
            continue
        if comment_id in seen:
            print(f"Skipped duplicate comment ID: {comment_id}")
            continue
        seen.add(comment_id)
        comment_ids.append(comment_id)

    return comment_ids, invalid_values

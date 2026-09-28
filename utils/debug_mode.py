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



# ==================== Debug and diagnostics ====================
DEBUG_MODE : bool = False

def is_debug_enabled() -> bool:
    return DEBUG_MODE

def debug_print(message: str):
    if is_debug_enabled():
        print(message)

def build_request_result(ok, html, error, status_code, final_url, redirected, response=None):
    result = {
        "ok": ok,
        "html": html,
        "error": error,
        "status_code": status_code,
        "final_url": final_url,
        "redirected": redirected
    }
    if is_debug_enabled():
        result.update({
            "content_type": response.headers.get("content-type") if response is not None else None,
            "content_length": len(response.text) if response is not None and response.text else 0
        })
    return result

def report_request_failure(error, status_code, final_url, exception=None):
    print(f"Request diagnosis: {error} | status={status_code} | final_url={final_url}")
    if exception is not None:
        debug_print(f"  request_error: {exception}")

def print_missing_cdiv_summary(reason, request_result):
    print(
        f"Gallery page diagnosis: {reason} "
        f"| status={request_result.get('status_code', 'N/A')} "
        f"| final_url={request_result.get('final_url', 'N/A')}"
    )

def print_missing_cdiv_debug(reason, title, url, request_result, body_text):
    debug_print(f"Gallery page diagnosis: {reason} | title={title or 'N/A'}")
    debug_print(f"  target_url: {url}")
    debug_print(f"  final_url: {request_result.get('final_url', 'N/A')}")
    debug_print(f"  redirected: {request_result.get('redirected', 'N/A')}")
    debug_print(f"  status_code: {request_result.get('status_code', 'N/A')}")
    debug_print(f"  content_type: {request_result.get('content_type', 'N/A')}")
    debug_print(f"  content_length: {request_result.get('content_length', 'N/A')}")
    snippet = body_text[:300].replace("\n", " ").strip()
    if snippet:
        debug_print(f"  page_text: {snippet}")
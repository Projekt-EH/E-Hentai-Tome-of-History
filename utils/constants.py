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

# ==================== Shared constants ====================
REQUEST_DELAY_MS = 1200
REQUEST_DELAY_JITTER = 0.50

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# ==================== Gallery version + comment deletion detection ====================
# E-Hentai renders "There are newer versions of this gallery available:" inside this
# container. When the container is present, the newest version listed in it is crawled
# instead of the URL that was requested.
NEWER_VERSION_DIV_ID = "gnd"

# Safety valve for chained version notices: every hop costs one extra page request, and a
# notice pointing back at a version we already fetched ends the chain anyway.
MAX_GALLERY_VERSION_HOPS = 5

# When True, comments that are stored in MongoDB for a crawled gallery but are missing from
# a successful crawl of that gallery are flagged as deleted (cleaned = True). Set to False
# to skip the database comparison entirely.
DELETION_DETECTION_ENABLED = True

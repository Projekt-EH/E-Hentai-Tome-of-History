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

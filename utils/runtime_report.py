"""Append-only, process-wide runtime diagnostics without retaining response data.

Place cleanup inside ``with report_run(label) as run`` so the final RSS sample
includes it. ``timed_request(category)`` belongs immediately around get/post,
not around parsing, backoff, or application-level retry loops. It is a no-op
outside a report, and is shared automatically with worker threads.
"""

import html
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import psutil
from .report_assets import HEADER as _HEADER, FOOTER as _FOOTER


_CATEGORIES = ("Gallery list GET", "Gallery GET", "Vote POST", "Other HTTP")
_REPORT_PATH = Path(__file__).resolve().parent.parent / "reports" / "runtime-report.html"
_MAX_REPORT_BYTES = 50_000_000
_ACTIVE_LOCK = threading.Lock()
_FILE_LOCK = threading.Lock()
_active_report = None
_MAX_POINTS = 1200


def _warn(message):
    # Diagnostics must not mask a task exception, including on a broken stderr.
    try:
        print(f"Runtime report warning: {message}", file=sys.stderr)
    except Exception:
        pass


def _append_entry(entry):
    """Append a whole entry, rotating before the standalone HTML exceeds its cap."""
    payload = entry.encode("utf-8")
    if len(_HEADER) + len(payload) + len(_FOOTER) > _MAX_REPORT_BYTES:
        raise OSError("one report entry exceeds the document size limit")
    with _FILE_LOCK:
        _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Discover the latest volume across restarts, without reading report history.
        prefix = _REPORT_PATH.stem + "-"
        volume = 1
        for candidate in _REPORT_PATH.parent.iterdir():
            if candidate.suffix == _REPORT_PATH.suffix and candidate.stem.startswith(prefix):
                number = candidate.stem[len(prefix):]
                if number.isascii() and number.isdigit():
                    volume = max(volume, int(number))
        while True:
            path = _REPORT_PATH if volume == 1 else _REPORT_PATH.with_name(
                f"{_REPORT_PATH.stem}-{volume}{_REPORT_PATH.suffix}"
            )
            try:
                stream = path.open("r+b")
            except FileNotFoundError:
                stream = path.open("w+b")
            with stream:
                size = stream.seek(0, 2)
                if size:
                    stream.seek(0)
                    if b"<!-- runtime-report-v2 -->" not in stream.read(256):
                        volume += 1
                        continue
                    if size < len(_FOOTER):
                        raise OSError("existing report has no recognized closing tags")
                    stream.seek(-len(_FOOTER), 2)
                    if stream.read(len(_FOOTER)) != _FOOTER:
                        raise OSError("existing report has no recognized closing tags")
                    if size + len(payload) > _MAX_REPORT_BYTES:
                        volume += 1
                        continue
                    stream.seek(-len(_FOOTER), 2)
                else:
                    stream.write(_HEADER)
                stream.write(payload)
                stream.write(_FOOTER)
                stream.truncate()
                stream.flush()
                os.fsync(stream.fileno())
                return


class _Run:
    def __init__(self, label):
        self.label = str(label)
        self.started_at = datetime.now(timezone.utc)
        self.started_ns = time.perf_counter_ns()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = None
        self.closed = False
        self.counts = [0] * len(_CATEGORIES)
        self.totals_ns = [0] * len(_CATEGORIES)
        self.points = []
        self.stride = 1
        self.sample_count = 0
        self.first_rss = None
        self.last_rss = None
        self.peak = None
        self.warnings = []
        self.database = None
        self.spool = None
        try:
            self.process = psutil.Process()
        except (psutil.Error, OSError):
            self.process = None
            self._warning("Process memory sampling is unavailable.")
        try:
            # Exact percentiles live on disk, not in an ever-growing Python list.
            self.spool = tempfile.TemporaryDirectory(prefix="runtime-report-")
            self.database = sqlite3.connect(
                str(Path(self.spool.name) / "durations.sqlite"),
                check_same_thread=False,
                isolation_level=None,
            )
            self.database.execute("PRAGMA journal_mode=OFF")
            self.database.execute("PRAGMA synchronous=OFF")
            self.database.execute("PRAGMA cache_size=-1024")
            self.database.execute("PRAGMA temp_store=FILE")
            self.database.execute("CREATE TABLE durations (category INTEGER, ns INTEGER, started INTEGER, ended INTEGER)")
        except (OSError, sqlite3.Error):
            self._discard_database()
            self._warning("Request duration storage is unavailable; p95 will be shown as a dash.")

    def _warning(self, message):
        if message not in self.warnings:
            self.warnings.append(message)
            _warn(message)

    def _discard_database(self):
        if self.database is not None:
            try:
                self.database.close()
            except sqlite3.Error:
                pass
            self.database = None

    def _start(self):
        self.sample_memory()
        self.thread = threading.Thread(
            target=self._sample_loop, name="runtime-report-rss", daemon=True
        )
        try:
            self.thread.start()
        except RuntimeError:
            self.thread = None
            self._warning("Periodic memory sampling could not start; boundary samples remain available.")

    def _sample_loop(self):
        while not self.stop.wait(1.0):
            self.sample_memory()

    def sample_memory(self):
        """Record current process RSS, e.g. immediately before/after cleanup.

        Sampling and request collection are thread-safe. The timeline is thinned
        adaptively to at most 1,200 resident points; peak RSS is tracked separately
        across every successful sample, not just the retained timeline points.
        """
        with self.lock:
            if self.closed or self.process is None:
                return
            try:
                rss = self.process.memory_info().rss
            except (psutil.Error, OSError):
                self._warning("Some process memory samples could not be read.")
                return
            point = ((time.perf_counter_ns() - self.started_ns) / 1e9, rss)
            if self.first_rss is None:
                self.first_rss = rss
            self.last_rss = rss
            if self.peak is None or rss > self.peak[1]:
                self.peak = point
            self.sample_count += 1
            if self.sample_count == 1 or self.sample_count % self.stride == 0:
                if len(self.points) >= _MAX_POINTS:
                    self.points = self.points[::2]
                    self.stride *= 2
                self.points.append(point)
            self.last_point = point

    def _record(self, category, started_ns, ended_ns):
        elapsed_ns = ended_ns - started_ns
        with self.lock:
            if self.closed:
                return
            self.counts[category] += 1
            self.totals_ns[category] += elapsed_ns
            if self.database is not None:
                try:
                    self.database.execute(
                        "INSERT INTO durations VALUES (?, ?, ?, ?)", (category, elapsed_ns, started_ns, ended_ns)
                    )
                except sqlite3.Error:
                    self._discard_database()
                    self._warning("Request duration storage failed; p95 will be shown as a dash.")

    def _statistics(self):
        """Exact latency quantiles and union of request intervals, including failures."""
        statistics = []
        for category in range(len(_CATEGORIES) + 1):
            count = self.counts[category] if category < len(_CATEGORIES) else sum(self.counts)
            summed = self.totals_ns[category] if category < len(_CATEGORIES) else sum(self.totals_ns)
            result = {"count": count, "average": summed / count if count else None,
                      "p95": None, "p95_average": None, "total": None, "parallel": False}
            statistics.append(result)
            if not count or self.database is None:
                continue
            where = " WHERE category = ?" if category < len(_CATEGORIES) else ""
            params = (category,) if where else ()
            rank = (95 * count + 99) // 100
            try:
                result["p95"], result["p95_average"] = self.database.execute(
                    "SELECT MAX(ns), AVG(ns) FROM (SELECT ns FROM durations" + where +
                    " ORDER BY ns LIMIT ?)", params + (rank,)
                ).fetchone()
                total = 0
                left = right = None
                for start, end in self.database.execute(
                    "SELECT started, ended FROM durations" + where + " ORDER BY started, ended", params
                ):
                    if right is None:
                        left, right = start, end
                    elif start <= right:
                        result["parallel"] |= start < right
                        right = max(right, end)
                    else:
                        total += right - left
                        left, right = start, end
                result["total"] = total + (right - left if right is not None else 0)
            except sqlite3.Error:
                self._warning("Some request timing statistics are unavailable.")
        return statistics

    def _chart(self, elapsed):
        if not self.points:
            return '<p class="note">Process memory data is unavailable.</p>'
        points = sorted(set(self.points + [self.last_point, self.peak]))
        low = min(point[1] for point in points) / 1048576
        high = max(point[1] for point in points) / 1048576
        padding = max((high - low) * 0.12, 1.0)
        low = max(0.0, low - padding)
        high += padding
        width, height = 890, 150
        duration = max(elapsed, points[-1][0], 0.001)
        coordinates = " ".join(
            f"{80 + t / duration * width:.2f},{180 - (rss / 1048576 - low) / (high - low) * height:.2f}"
            for t, rss in points
        )
        return (
            '<svg class="chart" viewBox="0 0 1000 225" role="img" '
            'aria-label="Process resident memory in MiB over elapsed seconds">'
            '<title>Process RSS timeline</title>'
            '<path d="M80 30H970 M80 105H970 M80 180H970" stroke="#dce5ef" fill="none"/>'
            f'<text x="70" y="34" text-anchor="end">{high:.1f}</text>'
            f'<text x="70" y="109" text-anchor="end">{(high + low) / 2:.1f}</text>'
            f'<text x="70" y="184" text-anchor="end">{low:.1f}</text>'
            '<text x="16" y="18">MiB</text>'
            f'<polyline points="{coordinates}" fill="none" stroke="#2563eb" '
            'stroke-width="2.5" stroke-linejoin="round"/>'
            '<text x="80" y="207">0 s</text>'
            f'<text x="970" y="207" text-anchor="end">{duration:.1f} s</text>'
            '</svg>'
            f'<p class="note">{self.sample_count:,} RSS samples, approximately one per second '
            'plus explicit boundary samples. Long timelines are thinned for bounded memory; '
            'the peak includes every successful sample. RSS covers this process, not child processes.</p>'
        )

    def _render(self, status, elapsed, ended_at):
        statistics = self._statistics()
        def cells(item):
            def ms(value):
                return "&mdash;" if value is None else f"{value / 1e6:,.2f}"
            values = [str(item["count"]), ms(item["average"]), ms(item["p95"]),
                      ms(item["p95_average"]), ms(item["total"]) + (" (Parallel)" if item["parallel"] else "")]
            return "".join(f"<td>{value}</td>" for value in values)
        rows = [f"<tr><td>{category}</td>{cells(statistics[index])}</tr>"
                for index, category in enumerate(_CATEGORIES)]
        cards = [("Wall time", f"{elapsed:,.2f} s")]
        for name, value in (("Start RSS", self.first_rss), ("End RSS", self.last_rss),
                            ("Peak RSS", self.peak[1] if self.peak else None)):
            cards.append((name, "&mdash;" if value is None else f"{value / 1048576:,.1f} MiB"))
        delta = None if self.first_rss is None else self.last_rss - self.first_rss
        cards.append(("RSS change", "&mdash;" if delta is None else f"{delta / 1048576:+,.1f} MiB"))
        card_html = "".join(
            f'<div class="card"><span>{name}</span><strong>{value}</strong></div>'
            for name, value in cards
        )
        warnings = "".join(f'<p class="warning">{html.escape(warning)}</p>' for warning in self.warnings)
        return (
            f'<article class="run" data-mode="{html.escape(self.label, quote=True)}" '
            f'data-start="{self.started_at.isoformat()}" data-duration="{elapsed:.6f}" data-status="{status}">'
            '<details><summary><div class="run-head">'
            f'<h2>{html.escape(self.label)}</h2><span class="badge {status}">{status}</span></div>'
            f'<p class="meta">{self.started_at.isoformat(timespec="seconds")} &rarr; '
            f'{ended_at.isoformat(timespec="seconds")}</p></summary>'
            f'<div class="cards">{card_html}</div>'
            '<h3>HTTP requests</h3><div class="table-wrap"><table><thead><tr>'
            '<th>Category</th><th>Count</th><th>Average (ms)</th><th>P95 (ms)</th>'
            '<th>P95 average (ms)</th><th>Total time (ms)</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody><tfoot><tr><td>All requests</td>'
            f'{cells(statistics[-1])}</tr></tfoot></table></div>'
            '<p class="note">P95 uses the nearest rank; P95 average is the average of the fastest '
            'ceil(95% × count) requests, including failed calls. Average is the per-request mean. '
            'Total time merges overlapping request intervals, excludes idle gaps, and is marked '
            'Parallel when calls overlap. The all-requests total merges across categories too. '
            'Retries and redirects are included in each logical call. No request secrets are stored.</p>'
            f'<h3>Resident memory</h3>{self._chart(elapsed)}{warnings}</details>\n</article>\n'
        )

    def _finish(self, status):
        self.stop.set()
        if self.thread is not None:
            self.thread.join()
        self.sample_memory()
        with self.lock:
            self.closed = True
            elapsed = (time.perf_counter_ns() - self.started_ns) / 1e9
            ended_at = datetime.now(timezone.utc)
            try:
                if any(self.counts):
                    _append_entry(self._render(status, elapsed, ended_at))
            except Exception as exc:
                # Do not expose paths/exception messages that may contain secrets.
                _warn(f"Could not append the HTML report ({type(exc).__name__}).")
            finally:
                self._discard_database()
                if self.spool is not None:
                    try:
                        self.spool.cleanup()
                    except OSError:
                        _warn("Could not remove temporary request duration storage.")


@contextmanager
def report_run(label):
    """Collect one run, append its HTML entry, and propagate task exceptions.

    The active run is process-wide, so ThreadPoolExecutor workers need no setup.
    Finish/join workers and release resources inside this context; its exit takes
    the final RSS sample after that cleanup. Nested/overlapping runs are invalid.
    """
    global _active_report
    with _ACTIVE_LOCK:
        if _active_report is not None:
            raise RuntimeError("Runtime reports cannot overlap")
        run = _Run(label)
        _active_report = run
    status = "success"
    try:
        run._start()
        yield run
    except (KeyboardInterrupt, SystemExit):
        status = "interrupted"
        raise
    except BaseException:
        status = "error"
        raise
    finally:
        with _ACTIVE_LOCK:
            _active_report = None
        try:
            run._finish(status)
        except Exception as exc:
            _warn(f"Could not finish the HTML report ({type(exc).__name__}).")


@contextmanager
def timed_request(category):
    """Time exactly one HTTP call, including raised calls and internal retries.

    Categories: Gallery list GET, Gallery GET, Vote POST, or Other HTTP.
    This context deliberately yields no response and never retains one.
    """
    try:
        index = _CATEGORIES.index(category)
    except ValueError:
        raise ValueError("Unknown runtime report request category") from None
    with _ACTIVE_LOCK:
        run = _active_report
    if run is None:
        yield
        return
    started_ns = time.perf_counter_ns()
    try:
        yield
    finally:
        run._record(index, started_ns, time.perf_counter_ns())

"""Static, offline HTML shell for appendable runtime-report volumes.

Records live between HEADER and FOOTER. The footer script discovers their
``data-mode``, ``data-start``, ``data-duration`` and ``data-status`` attributes;
record bodies remain ordinary HTML inside a native ``details`` element.
"""

HEADER = """<!doctype html>
<!-- runtime-report-v2 -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Runtime diagnostics</title>
<style>
:root{color-scheme:light;--ink:#172b45;--muted:#5e7088;--line:#dce5ef;--blue:#2563eb;--success:#16804a;--interrupted:#b77900;--error:#dc3434}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:#eef3f9;color:var(--ink);font:15px/1.6 system-ui,sans-serif}
main{max-width:1120px;margin:auto;padding:32px 20px 60px}h1{font-size:30px;margin:0}h2{font-size:21px;margin:0;overflow-wrap:anywhere}h3{font-size:16px;margin:24px 0 10px}
.subtitle,.note{color:var(--muted)}.subtitle{margin:4px 0 24px}.note{font-size:12px;margin:10px 0 0}
.overview,.run{background:white;border:1px solid var(--line);border-radius:16px;padding:24px;box-shadow:0 6px 24px #172b4508}
.filters{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:14px}.filter{display:flex;flex-direction:column;gap:5px;min-width:190px;flex:1}.filter:last-child{flex:2}.filter label{font-size:13px;font-weight:650}
select{width:100%;min-width:0;max-width:100%;padding:10px 32px 10px 12px;border:1px solid #b8c8dc;border-radius:8px;background:white;color:var(--ink);font:inherit}
select:focus-visible,summary:focus-visible{outline:3px solid var(--blue);outline-offset:3px}
.report-count{color:var(--muted);margin:8px 0 18px;font-size:13px}.overview h2{font-size:18px}.scatter-wrap{overflow-x:auto;margin-top:8px}.scatter{width:100%;min-width:640px;height:auto;display:block}
svg text{font:12px system-ui,sans-serif;fill:var(--muted)}.grid-line{stroke:var(--line);stroke-width:1}.axis-line{stroke:#91a5bf;stroke-width:1}.axis-label{font-weight:600}
.plot-point{stroke:white;stroke-width:1.5;cursor:pointer}.plot-point:hover,.plot-point:focus{stroke:var(--ink);stroke-width:3;outline:none}.plot-point[aria-pressed="true"]{stroke:var(--ink);stroke-width:3}
.plot-success{fill:var(--success)}.plot-interrupted{fill:var(--interrupted)}.plot-error{fill:var(--error)}.plot-unknown{fill:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:8px 20px;list-style:none;margin:0;padding:0;color:var(--muted);font-size:12px}.legend li{display:flex;align-items:center;gap:7px}.swatch{width:10px;height:10px;display:inline-block;border-radius:50%}.swatch.success{background:var(--success)}.swatch.interrupted{background:var(--interrupted)}.swatch.error{background:var(--error)}
.run{display:none;margin:24px 0}.run.is-selected{display:block}.run>details>summary{cursor:pointer;font-weight:650;overflow-wrap:anywhere}.run>details[open]>summary{padding-bottom:18px;margin-bottom:18px;border-bottom:1px solid var(--line)}
.run-head{display:flex;align-items:center;justify-content:space-between;gap:16px}.badge{border-radius:20px;padding:3px 12px;font-size:12px;font-weight:700;text-transform:uppercase;white-space:nowrap}.badge.success{background:#dcfce7;color:#166534}.badge.interrupted{background:#fef3c7;color:#92400e}.badge.error{background:#fee2e2;color:#991b1b}
.meta{color:var(--muted);font-size:13px;margin:8px 0 20px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:10px}.card{background:#f5f8fc;border-radius:10px;padding:12px}.card span{display:block;font-size:12px;color:var(--muted)}.card strong{font-size:20px;font-variant-numeric:tabular-nums}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:11px 12px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:var(--muted);font-size:12px;font-weight:600;background:#f8fafc}tfoot{font-weight:700}
.chart{width:100%;height:auto;display:block;background:#f8fafc;border:1px solid var(--line);border-radius:10px}.warning{color:#92400e;background:#fffbeb;border-radius:8px;padding:10px;font-size:13px}
@media(max-width:600px){main{padding:20px 10px}.overview,.run{padding:16px}.run-head{align-items:flex-start}h1{font-size:25px}h2{font-size:18px}th,td{padding:9px 7px}.filter{flex-basis:100%}}
@media print{body{background:white}main{max-width:none;padding:0}.overview,.run{box-shadow:none;break-inside:avoid}.filters{display:none}}
</style>
<noscript><style>.run{display:block}.overview{display:none}</style></noscript>
</head>
<body>
<main>
<h1>Runtime diagnostics</h1>
<p class="subtitle">Request timing and process memory, recorded one run or round at a time. All timestamps are UTC.</p>
<section class="overview" aria-labelledby="overview-heading">
<h2 id="overview-heading">Run overview</h2>
<div class="filters">
<div class="filter"><label for="mode-filter">Mode</label><select id="mode-filter"><option value="">All modes</option></select></div>
<div class="filter"><label for="run-filter">Run / round</label><select id="run-filter" aria-controls="record-list" disabled><option>No records</option></select></div>
</div>
<p id="report-count" class="report-count" role="status" aria-live="polite"></p>
<h2 id="scatter-heading">Elapsed time by start time</h2>
<div class="scatter-wrap"><svg id="run-scatter" class="scatter" viewBox="0 0 1000 330" role="group" aria-labelledby="scatter-title scatter-description"><title id="scatter-title">Run and round wall times</title><desc id="scatter-description">Start time in UTC on the horizontal axis, elapsed wall seconds on the vertical axis. Select a point with a click or use Tab and Enter or Space to open its record.</desc><g id="scatter-axes" aria-hidden="true"></g><g id="scatter-points" role="group" aria-label="Run and round records"></g></svg></div>
<ul class="legend" aria-label="Run status"><li><span class="swatch success" aria-hidden="true"></span>Success</li><li><span class="swatch interrupted" aria-hidden="true"></span>Interrupted</li><li><span class="swatch error" aria-hidden="true"></span>Error</li></ul>
<p id="scatter-note" class="note">Choose a mode to filter the chart and records. Click a point to open that record; only the selected record is displayed below.</p>
</section>
<noscript><p class="warning">JavaScript is disabled. Filters and the overview chart are unavailable; expand individual records below to read them.</p></noscript>
<div id="record-list">
""".encode("utf-8")

FOOTER = r"""
</div>
<script>
(function () {
    'use strict';
    const modeFilter = document.getElementById('mode-filter');
    const runFilter = document.getElementById('run-filter');
    const count = document.getElementById('report-count');
    const axes = document.getElementById('scatter-axes');
    const points = document.getElementById('scatter-points');
    const note = document.getElementById('scatter-note');
    const ns = 'http://www.w3.org/2000/svg';
    const seconds = new Intl.NumberFormat('en-US', {maximumFractionDigits: 2});
    const records = Array.from(document.querySelectorAll('#record-list > article.run'), function (element, index) {
        return {
            element: element,
            index: index,
            mode: element.dataset.mode || 'Unnamed mode',
            start: Date.parse(element.dataset.start),
            duration: Number(element.dataset.duration),
            status: element.dataset.status || 'unknown'
        };
    });
    let visible = [];
    let selected = null;
    const pointByRecord = new Map();
    function utc(value) {
        return Number.isFinite(value) ? new Date(value).toISOString().slice(0, 19).replace('T', ' ') : 'Unknown start';
    }
    function label(record) {
        return '#' + (record.index + 1) + ' · ' + record.mode + ' · ' + utc(record.start) + ' UTC · ' + seconds.format(record.duration) + ' s · ' + record.status;
    }
    function option(value, text) {
        const item = document.createElement('option');
        item.value = value;
        item.textContent = text;
        return item;
    }
    function svg(tag, attrs, text) {
        const element = document.createElementNS(ns, tag);
        Object.entries(attrs).forEach(function (entry) { element.setAttribute(entry[0], entry[1]); });
        if (text !== undefined) element.textContent = text;
        return element;
    }
    function selectRecord(record, open, scroll) {
        if (selected && selected !== record) {
            selected.element.hidden = true;
            selected.element.classList.remove('is-selected');
            const details = selected.element.querySelector('details');
            if (details) details.open = false;
            const previous = pointByRecord.get(selected);
            if (previous) { previous.setAttribute('aria-pressed', 'false'); previous.setAttribute('r', '5'); }
        }
        selected = record;
        if (!record) return;
        record.element.hidden = false;
        record.element.classList.add('is-selected');
        runFilter.value = String(record.index);
        const details = record.element.querySelector('details');
        if (details && open) details.open = true;
        const point = pointByRecord.get(record);
        if (point) { point.setAttribute('aria-pressed', 'true'); point.setAttribute('r', '7'); }
        if (scroll) {
            const summary = details ? details.querySelector('summary') : null;
            if (summary) summary.focus({preventScroll: true});
            record.element.scrollIntoView({block: 'start'});
        }
    }
    function drawChart() {
        axes.replaceChildren();
        points.replaceChildren();
        pointByRecord.clear();
        const plotted = visible.filter(function (record) {
            return Number.isFinite(record.start) && Number.isFinite(record.duration) && record.duration >= 0;
        });
        if (!plotted.length) {
            axes.appendChild(svg('text', {x: 500, y: 150, 'text-anchor': 'middle'}, 'No elapsed-time records to plot.'));
            return;
        }
        let earliest = plotted[0].start;
        let latest = earliest;
        let maximum = 0;
        plotted.forEach(function (record) {
            earliest = Math.min(earliest, record.start);
            latest = Math.max(latest, record.start);
            maximum = Math.max(maximum, record.duration);
        });
        const padding = earliest === latest ? 30000 : Math.max((latest - earliest) * 0.04, 1);
        const start = earliest - padding;
        const end = latest + padding;
        const ceiling = Math.max(maximum * 1.08, 1);
        const left = 84, right = 972, top = 30, bottom = 242;
        for (let i = 0; i <= 4; i++) {
            const y = bottom - (bottom - top) * i / 4;
            axes.appendChild(svg('line', {x1: left, y1: y, x2: right, y2: y, 'class': 'grid-line'}));
            axes.appendChild(svg('text', {x: left - 12, y: y + 4, 'text-anchor': 'end'}, seconds.format(ceiling * i / 4)));
            const x = left + (right - left) * i / 4;
            const date = utc(start + (end - start) * i / 4);
            axes.appendChild(svg('line', {x1: x, y1: bottom, x2: x, y2: bottom + 5, 'class': 'axis-line'}));
            const anchor = i === 0 ? 'start' : (i === 4 ? 'end' : 'middle');
            axes.appendChild(svg('text', {x: x, y: bottom + 23, 'text-anchor': anchor}, date.slice(0, 10)));
            axes.appendChild(svg('text', {x: x, y: bottom + 40, 'text-anchor': anchor}, date.slice(11)));
        }
        axes.appendChild(svg('path', {d: 'M' + left + ' ' + top + 'V' + bottom + 'H' + right, 'class': 'axis-line', fill: 'none'}));
        axes.appendChild(svg('text', {x: 18, y: 16, 'class': 'axis-label'}, 'Wall time (s)'));
        axes.appendChild(svg('text', {x: (left + right) / 2, y: 315, 'text-anchor': 'middle', 'class': 'axis-label'}, 'Start time (UTC)'));
        plotted.forEach(function (record) {
            const status = ['success', 'interrupted', 'error'].includes(record.status) ? record.status : 'unknown';
            const point = svg('circle', {
                cx: left + (record.start - start) / (end - start) * (right - left),
                cy: bottom - record.duration / ceiling * (bottom - top),
                r: 5, 'class': 'plot-point plot-' + status,
                role: 'button', tabindex: 0, 'aria-label': 'Open ' + label(record), 'aria-pressed': 'false'
            });
            point.appendChild(svg('title', {}, label(record)));
            point.addEventListener('click', function () { selectRecord(record, true, true); });
            point.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    selectRecord(record, true, true);
                }
            });
            points.appendChild(point);
            pointByRecord.set(record, point);
        });
    }
    function applyFilter() {
        const mode = modeFilter.value;
        visible = records.filter(function (record) { return mode === '' || record.mode === mode; });
        runFilter.replaceChildren();
        // Newest first, with append order breaking equal timestamps.
        const newest = visible.slice().sort(function (a, b) {
            return ((Number.isFinite(b.start) ? b.start : 0) - (Number.isFinite(a.start) ? a.start : 0)) || b.index - a.index;
        });
        newest.forEach(function (record) { runFilter.appendChild(option(String(record.index), label(record))); });
        runFilter.disabled = !visible.length;
        if (!visible.length) runFilter.appendChild(option('', 'No records'));
        count.textContent = visible.length + ' of ' + records.length + ' records' + (mode === '' ? ' · all modes' : ' · ' + mode) + '. Only the selected record is displayed; expand its summary for details.';
        const next = visible.includes(selected) ? selected : (newest[0] || null);
        drawChart();
        selectRecord(next, false, false);
        const invalid = visible.filter(function (record) { return !pointByRecord.has(record); }).length;
        note.textContent = 'Choose a mode to filter the chart and records. Click a point to open that record, or use Tab and Enter or Space. Each point is one run or round.' + (invalid ? ' ' + invalid + ' records have no plottable timing data.' : '');
    }
    const modes = Array.from(new Set(records.map(function (record) { return record.mode; }))).sort();
    modes.forEach(function (mode) { modeFilter.appendChild(option(mode, mode)); });
    records.forEach(function (record) {
        record.element.hidden = true;
        const details = record.element.querySelector('details');
        if (details) details.open = false;
    });
    modeFilter.addEventListener('change', applyFilter);
    runFilter.addEventListener('change', function () {
        const record = visible.find(function (item) { return String(item.index) === runFilter.value; });
        if (record) selectRecord(record, true, false);
    });
    applyFilter();
}());
</script>
</main>
</body>
</html>
""".encode("utf-8")

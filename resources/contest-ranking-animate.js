/* Contest ranking "score jump" animations.
 * Lives OUTSIDE of contest-ranking.js / contest-replay.js on purpose.
 *
 * It wraps window.renderRankingTable and, on every backend poll
 * (isNewDataFromBackend === true), diffs the incoming ranking JSON against the
 * previous one. For every user whose score strictly increased we queue a
 * visual event:
 *   - the row "pops" (scale up) while FLIP-sliding up to its new slot
 *   - the recently improved problem cell's number counts up old -> new
 *   - the total score cell counts up old -> new
 * Equal/lower scores produce no animation (only a subtle FLIP slide when rows
 * get displaced). Multiple events play one after another, ordered by the
 * earliest best-submission time of the changed problems.
 */

(function ($) {
    'use strict';

    // ─── Tuning knobs ─────────────────────────────────────────────────────────
    var CONFIG = {
        rowAnimMs:      1400, // row pop + move duration (matches @keyframes)
        cellStartMs:    420,  // when the number count-up starts after the poll
        cellGapMs:      220,  // stagger between problem cells of one user
        scoreTweenMs:  1100,  // count-up duration for one number
        totalDelayMs:  180,   // extra delay before the total score starts counting
        betweenUsersMs: 600,  // pause before the next user's animation
        flashMs:       1200,  // cell highlight lifetime
    };

    var reduceMotion = window.matchMedia &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // ─── CSS (injected once, keeps existing stylesheets untouched) ────────────
    // Transforms are applied per <td> (the row's cells) because a `transform`
    // on a <tr> element is unreliable across browsers.
    var ANIM_CSS = [
        '.rank-row-improve td{',
        '  animation: rankRankRowImprove ' + CONFIG.rowAnimMs + 'ms cubic-bezier(.22,.61,.36,1) both;',
        '  will-change: transform;',
        '}',
        '@keyframes rankRankRowImprove{',
        '  0%   { transform: translateY(var(--rk-dy,0px)) scale(1); }',
        '  12%  { transform: translateY(var(--rk-dy,0px)) scale(1.055); }',
        '  32%  { transform: translateY(calc(var(--rk-dy,0px) * .40)) scale(1); }',
        '  100% { transform: translateY(0) scale(1); }',
        '}',
        '.rank-name-flash{ animation: rankRankNameFlash 1200ms ease-out; }',
        '@keyframes rankRankNameFlash{',
        '  0%   { background-color: rgba(255,240,170,.55); }',
        '  100% { background-color: transparent; }',
        '}',
        '.rank-cell-flash{',
        '  animation: rankRankCellFlash 1200ms ease-out;',
        '  border-radius: 4px;',
        '  box-shadow: inset 0 0 0 2px #30c25e;',
        '}',
        '@keyframes rankRankCellFlash{',
        '  0%   { background-color: rgba(48,194,94,.38); }',
        '  60%  { background-color: rgba(48,194,94,.16); }',
        '  100% { background-color: transparent; }',
        '}',
        '.rank-count{ display:inline-block; font-variant-numeric: tabular-nums; }',
        '@media (prefers-reduced-motion: reduce){',
        '  .rank-row-improve td, .rank-name-flash, .rank-cell-flash{ animation: none !important; }',
        '}',
    ].join('\n');

    (function injectStyles() {
        if (document.getElementById('rank-anim-style')) return;
        var style = document.createElement('style');
        style.id = 'rank-anim-style';
        style.textContent = ANIM_CSS;
        (document.head || document.documentElement).appendChild(style);
    })();

    // ─── Utilities ────────────────────────────────────────────────────────────
    function fmtPoints(pts, precision) {
        if (pts === null || pts === undefined || isNaN(pts)) return '0';
        if (precision === 0) return String(Math.round(pts));
        return parseFloat(parseFloat(pts).toFixed(precision)).toString();
    }

    function scoreOf(p) { return p ? (p.score || 0) : 0; }

    function probPts(p, pid) {
        var fd = (p && p.format_data) || {};
        var entry = fd[pid];
        return entry ? (entry.points || 0) : 0;
    }

    function probTime(p, pid) {
        var fd = (p && p.format_data) || {};
        var entry = fd[pid];
        return entry ? (entry.time || 0) : 0;
    }

    function byId(list) {
        var m = {};
        for (var i = 0; i < list.length; i++) m[list[i].id] = list[i];
        return m;
    }

    // ─── Row geometry (FLIP) ─────────────────────────────────────────────────
    // #ranking-table tbody rows are rendered in the exact order of
    // data.participations, followed by the single "Total AC" row.
    function getTable() {
        var container = document.getElementById('ranking-container');
        if (!container) return null;
        var table = container.querySelector('#ranking-table');
        if (!table || !table.tBodies.length) return null;
        return table;
    }

    function captureRows(data) {
        var table = getTable();
        if (!table) return [];
        var trs = Array.prototype.slice.call(table.tBodies[0].rows);
        var cTop = table.parentElement.getBoundingClientRect().top;
        var parts = data.participations || [];
        return parts.map(function (p, i) {
            var row = trs[i];
            var visible = row && row.offsetParent !== null;
            return {
                pId: p.id,
                top: visible ? (row.getBoundingClientRect().top - cTop) : null,
            };
        });
    }

    function buildRowById(data) {
        var table = getTable();
        if (!table) return {};
        var trs = Array.prototype.slice.call(table.tBodies[0].rows);
        var parts = data.participations || [];
        var map = {};
        for (var i = 0; i < parts.length; i++) map[parts[i].id] = trs[i];
        return map;
    }

    // Problem <th> order == problem <td> order inside a row (the header places
    // the optional penalty/badge/rating columns in the same spots as the body).
    function buildProblemColMap() {
        var table = getTable();
        if (!table) return {};
        var ths = table.querySelectorAll('thead tr th');
        var map = {};
        for (var i = 0; i < ths.length; i++) {
            var codeEl = ths[i].querySelector('.problem-code');
            if (codeEl) map[codeEl.textContent.trim()] = i;
        }
        return map;
    }

    // Rows displaced by a ranking change slide down gently; the improved rows
    // get their own pop-and-slide keyframe instead.
    function applyCellsTransform(row, transition, transform) {
        for (var c = 0; c < row.cells.length; c++) {
            row.cells[c].style.transition = transition;
            row.cells[c].style.transform = transform;
        }
    }

    function applyFlipDisplacement(oldRows, newRows, rowById, improvedIds) {
        var oldTop = {};
        for (var i = 0; i < oldRows.length; i++) oldTop[oldRows[i].pId] = oldRows[i].top;
        for (var i = 0; i < newRows.length; i++) {
            var nr = newRows[i];
            var row = rowById[nr.pId];
            if (!row || nr.top === null || oldTop[nr.pId] === undefined ||
                oldTop[nr.pId] === null || improvedIds[nr.pId]) continue;
            var dy = oldTop[nr.pId] - nr.top;
            if (Math.abs(dy) < 1) continue;
            var dur = Math.min(500, Math.abs(dy / 8) + 220);
            applyCellsTransform(row, 'none', 'translateY(' + dy + 'px)');
            void row.offsetHeight;
            applyCellsTransform(row, 'transform ' + dur + 'ms ease-out', 'translateY(0)');
            setTimeout(function () { applyCellsTransform(row, '', ''); }, dur + 80);
        }
    }

    // ─── Number count-up ──────────────────────────────────────────────────────
    var NUM_RE = /^[0-9]+(\.[0-9]+)?$/;

    function firstScoreTextNode(container) {
        var walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
            acceptNode: function (node) {
                if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_SKIP;
                var el = node.parentElement;
                while (el && el !== container) {
                    if (el.classList &&
                        (el.classList.contains('solving-time') || el.classList.contains('solving-time-minute'))) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    el = el.parentElement;
                }
                return NodeFilter.FILTER_ACCEPT;
            },
        });
        return walker.nextNode();
    }

    // Wraps the score number of a cell in a counting <span>. Returns the span,
    // or null when the cell has no countable number (ICPC tries, pending '?').
    function wrapScoreText(cell) {
        if (!cell) return null;
        var a = cell.querySelector('a');
        var container = a || cell;
        var existing = container.querySelector('.rank-count');
        if (existing) return existing;
        var tn = firstScoreTextNode(container);
        if (!tn) return null;
        var text = tn.nodeValue.trim();
        if (!NUM_RE.test(text)) return null; // e.g. "3 tries", "100?""
        var span = document.createElement('span');
        span.className = 'rank-count';
        span.textContent = text;
        tn.parentNode.insertBefore(span, tn);
        tn.parentNode.removeChild(tn);
        return span;
    }

    function tweenNumber(span, from, to, precision, ms) {
        var fmt = function (v) { return fmtPoints(v, precision); };
        if (reduceMotion || ms <= 0) {
            span.textContent = fmt(to);
            return;
        }
        var start = performance.now();
        function frame(now) {
            var t = Math.min(1, (now - start) / ms);
            var eased = 1 - Math.pow(1 - t, 3);
            span.textContent = fmt(from + (to - from) * eased);
            if (t < 1) requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
    }

    // ─── Event diffing ────────────────────────────────────────────────────────
    function buildEvents(prev, data, rowById) {
        var oldById = byId(prev.participations || []);
        var events = [];
        (data.participations || []).forEach(function (np) {
            var op = oldById[np.id];
            if (!op || op.is_disqualified) return;
            if (!(scoreOf(np) > scoreOf(op) + 1e-9)) return; // equal/lower -> no change
            var changes = [];
            var earliest = Infinity;
            (data.problems || []).forEach(function (prob) {
                var pid = String(prob.id);
                var from = probPts(op, pid), to = probPts(np, pid);
                if (to > from + 1e-9) {
                    var t = probTime(np, pid);
                    changes.push({
                        code: prob.code,
                        from: from,
                        to: to,
                        time: t,
                    });
                    if (t < earliest) earliest = t;
                }
            });
            var row = rowById[np.id];
            if (!row || row.offsetParent === null) return; // hidden by filter
            events.push({
                pId: np.id,
                row: row,
                fromScore: scoreOf(op),
                toScore: scoreOf(np),
                changes: changes,
                time: isFinite(earliest) ? earliest : 0,
            });
        });
        events.sort(function (a, b) { return a.time - b.time; }); // earliest first
        return events;
    }

    function resolveColumns(events) {
        var colMap = buildProblemColMap();
        events.forEach(function (e) {
            e.changes.forEach(function (c) {
                var col = colMap[c.code];
                c.cell = col !== undefined ? e.row.cells[col] : null;
            });
        });
        return events;
    }

    // ─── Playback (runs one user's event) ─────────────────────────────────────
    var animToken = 0;

    function playEvent(e, precision) {
        var row = e.row;
        if (!row) return;
        row.style.setProperty('--rk-dy', (e.dy || 0) + 'px');
        row.classList.add('rank-row-improve');
        setTimeout(function () { row.classList.remove('rank-row-improve'); }, CONFIG.rowAnimMs + 80);

        var nameCell = row.querySelector('.user-name');
        if (nameCell) {
            nameCell.classList.add('rank-name-flash');
            setTimeout(function () { nameCell.classList.remove('rank-name-flash'); }, CONFIG.flashMs);
        }

        var totalCell = row.querySelector('.user-points');

        e.changes.forEach(function (c, i) {
            var cell = c.cell;
            if (!cell) return;
            cell.classList.add('rank-cell-flash');
            setTimeout(function () { cell.classList.remove('rank-cell-flash'); }, CONFIG.flashMs);
            var span = wrapScoreText(cell);
            if (span) {
                span.textContent = fmtPoints(c.from, precision);
                setTimeout(function () {
                    tweenNumber(span, c.from, c.to, precision, CONFIG.scoreTweenMs);
                }, CONFIG.cellStartMs + i * CONFIG.cellGapMs);
            }
        });

        if (totalCell) {
            var totalSpan = wrapScoreText(totalCell);
            if (totalSpan) {
                totalSpan.textContent = fmtPoints(e.fromScore, precision);
                setTimeout(function () {
                    tweenNumber(totalSpan, e.fromScore, e.toScore, precision, CONFIG.scoreTweenMs);
                }, CONFIG.cellStartMs + CONFIG.totalDelayMs + Math.max(0, e.changes.length - 1) * CONFIG.cellGapMs);
            }
        }
    }

    function runQueue(events, precision) {
        var token = ++animToken;
        var i = 0;
        function step() {
            if (token !== animToken || i >= events.length) return;
            var e = events[i++];
            var lastTweenEnd = CONFIG.cellStartMs +
                (e.changes.length ? (e.changes.length - 1) * CONFIG.cellGapMs + CONFIG.scoreTweenMs : 0);
            var doneAt = Math.max(CONFIG.rowAnimMs, CONFIG.cellStartMs + CONFIG.totalDelayMs + CONFIG.scoreTweenMs, lastTweenEnd) + 60;
            playEvent(e, precision);
            setTimeout(step, doneAt + CONFIG.betweenUsersMs);
        }
        step();
    }

    // ─── Entry: wrap renderRankingTable ──────────────────────────────────────
    var lastData = null;
    var originalRenderRankingTable = window.renderRankingTable;

    function animateRankingChange(prev, data, oldRows) {
        var newRows = captureRows(data);
        var rowById = buildRowById(data);
        var events = buildEvents(prev, data, rowById);
        if (!events.length) return;

        resolveColumns(events);

        var oldTop = {};
        (oldRows || []).forEach(function (r) { oldTop[r.pId] = r.top; });
        var newTop = {};
        newRows.forEach(function (r) { newTop[r.pId] = r.top; });

        var improvedIds = {};
        events.forEach(function (e) {
            improvedIds[e.pId] = true;
            var dy = (oldTop[e.pId] !== undefined && oldTop[e.pId] !== null && newTop[e.pId] !== null)
                ? oldTop[e.pId] - newTop[e.pId]
                : 0;
            e.dy = Math.max(0, Math.round(dy));
        });
        applyFlipDisplacement(oldRows, newRows, rowById, improvedIds);

        var precision = (data.contest && data.contest.points_precision) || 0;
        runQueue(events, precision);
    }

    if (typeof originalRenderRankingTable !== 'function') {
        // Should not happen (this script loads after contest-ranking.js), but
        // degrade gracefully instead of breaking the page if ordering changes.
        return;
    }

    window.renderRankingTable = function (data, isNewDataFromBackend) {
        var prev = lastData;
        var oldRows = prev ? captureRows(prev) : null;
        var result = originalRenderRankingTable(data, isNewDataFromBackend);
        lastData = data;
        if (prev && isNewDataFromBackend === true && !reduceMotion) {
            try {
                animateRankingChange(prev, data, oldRows);
            } catch (err) {
                if (window.console && console.error) console.error('ranking animation error:', err);
            }
        }
        return result;
    };

})(jQuery);
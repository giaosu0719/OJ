/**
 * Disqualification reason picker for the contest ranking table.
 *
 * Replaces the old "click the bin icon -> confirm()" flow:
 *   - clicking the bin opens a modal with the preset reasons plus a "Khác"
 *     option that reveals a free-text box;
 *   - submitting POSTs `disqualify_action=disqualify` plus the chosen code and
 *     detail, so the server can store and validate them;
 *   - disqualified rows get a callout row rendered by
 *     `window.buildDisqualifyNoteRow`, which `contest-ranking.js` calls from
 *     `buildUserRow()`.
 *
 * The reason list comes from the server (`contest.disqualify_reasons`, built
 * from ContestParticipation.DISQUALIFY_REASON_CHOICES) so the model stays the
 * single source of truth.
 *
 * Why this does not use Featherlight: the bundled featherlight.min.js is 1.2.1
 * and its `jquery` content filter does `$(content).clone(true)`, so the node the
 * user ticks is never the node the handlers close over -- every read came back
 * empty and the form silently did nothing. The bundled featherlight.scss is
 * also written against 1.7.14. So the overlay lives here instead, and the state
 * is read from the live element the user is actually interacting with.
 */
(function () {
    'use strict';

    var OTHER_FALLBACK = 'other';
    var TITLE_THRESHOLD = 30;

    // ─── Helpers ──────────────────────────────────────────────────────────────

    function getCsrfToken() {
        var match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? match[1] : '';
    }

    function escapeHtml(text) {
        if (typeof window.escapeHtml === 'function') return window.escapeHtml(text);
        return String(text === null || text === undefined ? '' : text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /** A title attribute is only useful when the text is long enough to clip. */
    function titleAttr(text) {
        var s = String(text === null || text === undefined ? '' : text);
        return s.length > TITLE_THRESHOLD ? ' title="' + escapeHtml(s) + '"' : '';
    }

    // ─── The note row shown under a disqualified participant ──────────────────

    window.buildDisqualifyNoteRow = function (participation, totalColspan) {
        var p = participation || {};
        var label = p.disqualify_reason_label || '';
        var detail = p.disqualify_reason_detail || '';

        // Nothing worth showing (e.g. disqualified straight from the admin).
        if (!label && !detail) return '';

        var html = '<tr class="disqualify-note-row">' +
            '<td colspan="' + (totalColspan || 1) + '">' +
            '<div class="disqualify-note">';

        // One line, no arrow: the disqualified-row background on the <td> above
        // is what visually ties the callout to that user. The detail is a
        // <span> inside the flex line, not a sibling below it, otherwise flex
        // would squeeze it onto the same row anyway.
        html += '<div class="disqualify-note-line">' +
            '<span class="disqualify-note-label">Đã bị truất quyền:</span> ' +
            '<span class="disqualify-note-value"' + titleAttr(label) + '>' +
            escapeHtml(label) + '</span>';

        if (detail) {
            // The em dash is inside the truncating span, so a clipped detail
            // renders as "Khác — Ghi chụp màn h…". The title is built from the
            // raw detail so hovering shows the bare text, without the dash.
            html += '<span class="disqualify-note-detail"' + titleAttr(detail) +
                '>— ' + escapeHtml(detail) + '</span>';
        }

        html += '</div></div></td></tr>';
        return html;
    };

    // ─── The dialog ───────────────────────────────────────────────────────────

    var openDialog = null;

    function closeDialog() {
        if (!openDialog) return;
        openDialog.$overlay.off('.disqualify');
        openDialog.$overlay.remove();
        $(document).off('.disqualify');
        openDialog = null;
    }

    function buildDialog(reasons, otherCode, $target) {
        closeDialog();

        var otherValue = otherCode || OTHER_FALLBACK;
        var formId = 'disqualify-reason-form';

        var $overlay = $('<div class="disqualify-overlay" role="dialog" aria-modal="true"></div>');
        var $dialog = $('<div class="disqualify-dialog"></div>').appendTo($overlay);

        var $form = $('<form></form>').attr('id', formId);
        $form.append('<h3 class="disqualify-dialog-title">Lý do truất quyền</h3>');
        $form.append(
            '<p class="disqualify-dialog-hint">Chọn một lý do để truất quyền tham dự này.</p>');

        var $choices = $('<div class="disqualify-reason-choices"></div>').appendTo($form);
        for (var i = 0; i < reasons.length; i++) {
            var reason = reasons[i];
            var inputId = formId + '-' + escapeHtml(reason.value);
            $choices.append(
                '<label class="disqualify-reason-choice" for="' + inputId + '">' +
                '<input type="radio" name="disqualify_reason" id="' + inputId + '"' +
                ' value="' + escapeHtml(reason.value) + '"> ' +
                escapeHtml(reason.label) +
                '</label>');
        }

        var $other = $('<div class="disqualify-reason-other"></div>').appendTo($form);
        $other.append('<label class="disqualify-other-label" for="' + formId +
            '-detail">Ghi rõ lý do</label>');
        $other.append('<textarea id="' + formId +
            '-detail" name="disqualify_reason_detail" rows="3"' +
            ' placeholder="Mô tả cụ thể lý do truất quyền..."></textarea>');
        $other.hide();

        $form.append('<div class="disqualify-dialog-error" style="display:none;"></div>');
        $form.append(
            '<div class="disqualify-dialog-buttons">' +
            '<button type="submit" class="button disqualify-dialog-submit">Truất quyền</button>' +
            '<button type="button" class="button button-cancel disqualify-dialog-cancel">Huỷ</button>' +
            '</div>');

        $dialog.append($form);
        $overlay.appendTo(document.body);

        // Every handler below reads the live $form the user is interacting with,
        // rather than a copy of it.
        $form.on('change', 'input[name=disqualify_reason]', function () {
            var checked = $form.find('input[name=disqualify_reason]:checked').val();
            $other.toggle(checked === otherValue);
        });
        $form.on('click', '.disqualify-dialog-cancel', function (e) {
            e.preventDefault();
            closeDialog();
        });
        $form.on('submit', function (e) {
            e.preventDefault();
            submit($form, $target, otherValue);
        });

        $overlay.on('click.disqualify', function (e) {
            if (e.target === $overlay[0]) closeDialog();
        });
        $(document).on('keydown.disqualify', function (e) {
            if (e.keyCode === 27) closeDialog();
        });

        openDialog = { $overlay: $overlay, $form: $form, $other: $other, otherValue: otherValue };

        var $first = $form.find('input[name=disqualify_reason]').first();
        if ($first.length) $first.trigger('focus');

        return openDialog;
    }

    // ─── Submit ───────────────────────────────────────────────────────────────

    function submit($form, $target, otherValue) {
        var $error = $form.find('.disqualify-dialog-error');
        var reason = $form.find('input[name=disqualify_reason]:checked').val();
        var detail = String($form.find('textarea[name=disqualify_reason_detail]').val() || '').trim();

        if (!reason) {
            $error.text('Vui lòng chọn một lý do.').show();
            return;
        }
        if (reason === otherValue && !detail) {
            $error.text('Vui lòng ghi rõ lý do cho mục "Khác".').show();
            return;
        }
        if (!$target || !$target.length) return;

        // Same shape as the old submitDisqualifyForm() in contest/ranking.html,
        // plus the reason fields and the explicit action.
        var form = document.createElement('form');
        form.method = 'post';
        form.action = $target.attr('data-action-url');
        form.style.display = 'none';

        function addField(name, value) {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = value;
            form.appendChild(input);
        }

        addField('csrfmiddlewaretoken', getCsrfToken());
        addField('participation', $target.attr('data-participation-id'));
        addField('disqualify_action', 'disqualify');
        addField('disqualify_reason', reason);
        if (reason === otherValue) addField('disqualify_reason_detail', detail);

        document.body.appendChild(form);
        form.submit();
    }

    // ─── Binding (re-run after every ranking re-render) ───────────────────────

    window.enableDisqualifyOperations = function () {
        $('a.disqualify-participation').each(function () {
            var $link = $(this);
            if ($link.data('disqualify-bound')) return;
            $link.data('disqualify-bound', true);

            $link.click(function (e) {
                e.preventDefault();

                var contestData = (window.RANKING_DATA && window.RANKING_DATA.contest) || {};
                buildDialog(contestData.disqualify_reasons || [],
                            contestData.disqualify_other_code || OTHER_FALLBACK, $link);
            });
        });
    };
})();

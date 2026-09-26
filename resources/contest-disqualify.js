/**
 * Disqualification reason picker for the contest ranking table.
 *
 * Replaces the old "click the bin icon -> confirm()" flow:
 *   - clicking the bin opens a Featherlight dialog with the preset reasons
 *     plus a "Khác" option that reveals a free-text box;
 *   - submitting POSTs `disqualify_action=disqualify` plus the chosen code and
 *     detail, so the server can store and validate them;
 *   - disqualified rows get a callout row rendered by
 *     `window.buildDisqualifyNoteRow`, which `contest-ranking.js` calls from
 *     `buildUserRow()`.
 *
 * The reason list comes from the server (`contest.disqualify_reasons`, built
 * from ContestParticipation.DISQUALIFY_REASON_CHOICES) so the model stays the
 * single source of truth.
 */
(function () {
    'use strict';

    var OTHER_FALLBACK = 'other';

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

    // ─── The note row shown under a disqualified participant ──────────────────

    window.buildDisqualifyNoteRow = function (participation, totalColspan) {
        var p = participation || {};
        var label = p.disqualify_reason_label || '';
        var detail = p.disqualify_reason_detail || '';

        // Nothing worth showing (e.g. disqualified straight from the admin).
        if (!label && !detail) return '';

        var html = '<tr class="disqualify-note-row">' +
            '<td colspan="' + (totalColspan || 1) + '">' +
            '<div class="disqualify-note">' +
            '<span class="disqualify-note-arrow" aria-hidden="true"></span>' +
            '<span class="disqualify-note-label">Đã bị truất quyền:</span> ' +
            '<span class="disqualify-note-value">' + escapeHtml(label) + '</span>';

        if (detail) {
            html += '<div class="disqualify-note-detail">' + escapeHtml(detail) + '</div>';
        }

        html += '</div></td></tr>';
        return html;
    };

    // ─── The dialog ───────────────────────────────────────────────────────────

    var dialogBuilt = false;

    function buildDialog(reasons, otherCode) {
        if (dialogBuilt) return $('#disqualify-reason-dialog');
        dialogBuilt = true;

        var $dialog = $('<div id="disqualify-reason-dialog" class="disqualify-dialog"></div>');

        var $form = $('<form id="disqualify-reason-form"></form>');
        $form.append('<h3>Lý do truất quyền</h3>');
        $form.append(
            '<p class="disqualify-dialog-hint">Chọn một lý do để truất quyền tham dự này.</p>');

        var $choices = $('<div class="disqualify-reason-choices"></div>').appendTo($form);
        for (var i = 0; i < reasons.length; i++) {
            var reason = reasons[i];
            var inputId = 'disqualify-reason-' + reason.value;
            $choices.append(
                '<label class="disqualify-reason-choice" for="' + escapeHtml(inputId) + '">' +
                '<input type="radio" name="disqualify_reason" id="' + escapeHtml(inputId) + '"' +
                ' value="' + escapeHtml(reason.value) + '"> ' +
                escapeHtml(reason.label) +
                '</label>');
        }

        var $other = $('<div class="disqualify-reason-other"></div>').appendTo($form);
        $other.append('<label class="disqualify-other-label" for="disqualify-reason-detail">Ghi rõ lý do</label>');
        $other.append('<textarea id="disqualify-reason-detail" name="disqualify_reason_detail" rows="3"' +
                      ' placeholder="Mô tả cụ thể lý do truất quyền..."></textarea>');

        $form.append('<div class="disqualify-dialog-error" style="display:none;"></div>');
        $form.append(
            '<div class="disqualify-dialog-buttons">' +
            '<button type="submit" class="button disqualify-dialog-submit">Truất quyền</button>' +
            '<button type="button" class="button button-cancel disqualify-dialog-cancel">Huỷ</button>' +
            '</div>');

        $dialog.append($form).appendTo(document.body);

        var otherValue = otherCode || OTHER_FALLBACK;
        $form.on('change', 'input[name=disqualify_reason]', function () {
            var isOther = $form.find('input[name=disqualify_reason]:checked').val() === otherValue;
            $other.toggle(isOther);
        });
        $form.on('click', '.disqualify-dialog-cancel', function () {
            $.featherlight.current().close();
        });
        $form.on('submit', function (e) {
            e.preventDefault();
            submit($form, $dialog);
        });

        $other.hide();
        return $dialog;
    }

    // ─── Submit ───────────────────────────────────────────────────────────────

    function submit($form, $dialog) {
        var $error = $form.find('.disqualify-dialog-error');
        var reason = $form.find('input[name=disqualify_reason]:checked').val();
        var detail = $.trim($form.find('textarea[name=disqualify_reason_detail]').val() || '');
        var otherValue = $form.data('other-code') || OTHER_FALLBACK;

        if (!reason) {
            $error.text('Vui lòng chọn một lý do.').show();
            return;
        }
        if (reason === otherValue && !detail) {
            $error.text('Vui lòng ghi rõ lý do cho mục "Khác".').show();
            return;
        }

        var $target = $dialog.data('target');
        if (!$target || !$target.length) return;

        // Same shape as the old submitDisqualifyForm() in contest/ranking.html,
        // plus the reason fields and the explicit action.
        var form = document.createElement('form');
        form.method = 'post';
        form.action = $target.data('action-url');
        form.style.display = 'none';

        function addField(name, value) {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            input.value = value;
            form.appendChild(input);
        }

        addField('csrfmiddlewaretoken', getCsrfToken());
        addField('participation', $target.data('participation-id'));
        addField('disqualify_action', 'disqualify');
        addField('disqualify_reason', reason);
        if (reason === otherValue) addField('disqualify_reason_detail', detail);

        document.body.appendChild(form);
        form.submit();
    }

    // ─── Binding (re-run after every ranking re-render) ───────────────────────

    window.enableDisqualifyOperations = function () {
        if (typeof $.featherlight !== 'function') return;

        $('a.disqualify-participation').each(function () {
            var $link = $(this);
            if ($link.data('disqualify-bound')) return;
            $link.data('disqualify-bound', true);

            $link.click(function (e) {
                e.preventDefault();

                var urlTemplates = (window.RANKING_DATA && window.RANKING_DATA.contest) || {};
                var reasons = urlTemplates.disqualify_reasons || [];
                var otherCode = urlTemplates.disqualify_other_code || OTHER_FALLBACK;

                var $dialog = buildDialog(reasons, otherCode);
                $dialog.data('other-code', otherCode);
                $dialog.data('target', $link);

                var $form = $dialog.find('#disqualify-reason-form');
                $form.find('input[name=disqualify_reason]').prop('checked', false);
                $form.find('textarea[name=disqualify_reason_detail]').val('');
                $form.find('.disqualify-reason-other').hide();
                $form.find('.disqualify-dialog-error').hide();

                $.featherlight($dialog, { closeOnOverlay: true });
            });
        });
    };
})();

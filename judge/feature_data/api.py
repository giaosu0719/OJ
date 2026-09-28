"""Read/write helpers for the feature-data store.

The disqualification reasons and the three social handles used to live in columns
on ``judge_contestparticipation`` / ``judge_profile``. They now live in a plain
JSON file (see ``docs/FEATURE_DATA.md``) so that removing them from the main
database needs no schema migration at all.

Two rules shape everything in this module:

1. Reads degrade, writes do not. If the file is missing or unreadable, a read
   returns "no data" (and says so in the log) so a scoreboard page still
   renders. A write raises, because silently dropping a disqualification reason
   would lose data the operator just typed.

2. Writes hit the JSON file *before* the primary database. The two stores
   cannot share a transaction, so if the second write fails the JSON entry is
   the one that is left behind -- an orphan reason next to a participation that
   is not flagged is harmless, whereas a flagged participation whose reason
   vanished is not.

Concurrency: several processes (web, celery, bridged) can hit this file, so every
mutation is done under an exclusive ``flock`` and published with
``os.replace`` on a temp file in the same directory. ``os.replace`` is atomic on
POSIX, so a reader never sees a half-written file.
"""

import errno
import json
import logging
import os
import tempfile
from contextlib import contextmanager

from django.conf import settings

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1

_EMPTY = {
    'version': FORMAT_VERSION,
    'disqualify': {},
    'social_handles': {},
}


class FeatureDataError(Exception):
    """Raised when feature data cannot be persisted."""


def get_path():
    return getattr(settings, 'FEATURE_DATA_PATH', None) or os.path.join(
        getattr(settings, 'BASE_DIR', os.getcwd()), 'feature_data.json')


def _empty():
    return json.loads(json.dumps(_EMPTY))


@contextmanager
def _locked(exclusive):
    """Hold a lock on ``<path>.lock`` for the duration of the block."""
    path = get_path()
    lock_path = path + '.lock'
    directory = os.path.dirname(path) or '.'
    if exclusive:
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as e:
            raise FeatureDataError('cannot create %s: %s' % (directory, e))

    if fcntl is None:  # pragma: no cover - non-POSIX fallback
        yield
        return

    handle = None
    try:
        handle = open(lock_path, 'a+')
        try:
            # The site processes run as 'oj' while this file may first be created
            # by root, and flock needs an open-for-write descriptor from whoever
            # comes next. Keep it group/other writable.
            os.chmod(lock_path, 0o666)
        except OSError:  # pragma: no cover - e.g. foreign filesystem
            logger.debug('cannot relax permissions on %s', lock_path, exc_info=True)
        fcntl.flock(handle, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        if handle is not None:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()


def _read():
    """Return the whole document, or a fresh empty one."""
    path = get_path()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError):
        # Includes json.JSONDecodeError, which is a ValueError.
        logger.warning(
            'Feature-data file %s is unreadable (%s); treating it as empty. '
            'Fix or restore the file before writing.', path, exc_info=True)
        return _empty()

    if not isinstance(data, dict):
        logger.warning('Feature-data file %s is not a JSON object; treating it as empty.', path)
        return _empty()

    # Be tolerant of a partially written or hand-edited file.
    document = _empty()
    for key in ('disqualify', 'social_handles'):
        section = data.get(key)
        if isinstance(section, dict):
            document[key] = section
    return document


def _write(document):
    """Publish ``document`` atomically. Caller must hold the exclusive lock."""
    path = get_path()
    directory = os.path.dirname(path) or '.'
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix='.feature_data-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(document, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
    except OSError as e:
        raise FeatureDataError('cannot write feature data to %s: %s' % (path, e))


def _mutate(section, key, value):
    """Read-modify-write one key of one section under the exclusive lock."""
    with _locked(exclusive=True):
        document = _read()
        table = document[section]
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
        _write(document)


# --- disqualification reasons -------------------------------------------------

def get_disqualify_reasons(participation_ids):
    """Map participation_id -> (reason, detail) for the given ids.

    Participations with no stored reason are simply absent from the result.
    """
    participation_ids = list(participation_ids)
    if not participation_ids:
        return {}

    with _locked(exclusive=False):
        table = _read()['disqualify']

    result = {}
    for raw_id in participation_ids:
        entry = table.get(str(raw_id))
        if isinstance(entry, dict):
            result[raw_id] = (entry.get('reason') or '', entry.get('detail') or '')
    return result


def set_disqualify_reason(participation, reason, detail=''):
    """Store the reason for a participation."""
    key = str(participation.id)
    _mutate('disqualify', key, {
        'contest': participation.contest_id,
        'reason': reason or '',
        'detail': detail or '',
    })
    return {'participation_id': participation.id,
            'reason': reason or '', 'detail': detail or ''}


def clear_disqualify_reason(participation):
    """Drop any stored reason for a participation."""
    _mutate('disqualify', str(participation.id), None)


# --- social handles -----------------------------------------------------------

def get_social_handles(user_ids):
    """Map user_id -> {'codeforces': str, 'discord': str, 'atcoder': str}."""
    user_ids = list(user_ids)
    if not user_ids:
        return {}

    with _locked(exclusive=False):
        table = _read()['social_handles']

    result = {}
    for raw_id in user_ids:
        entry = table.get(str(raw_id))
        if isinstance(entry, dict):
            result[raw_id] = {
                'codeforces': entry.get('codeforces') or '',
                'discord': entry.get('discord') or '',
                'atcoder': entry.get('atcoder') or '',
            }
    return result


def get_social_handle(user_id):
    """Handles for one user, as a dict of empty strings when unset."""
    return get_social_handles([user_id]).get(user_id) or {
        'codeforces': '', 'discord': '', 'atcoder': '',
    }


def save_social_handle(profile, codeforces='', discord='', atcoder=''):
    """Store handles for a profile. Blank input clears the stored value."""
    _mutate('social_handles', str(profile.id), {
        'codeforces': codeforces or '',
        'discord': discord or '',
        'atcoder': atcoder or '',
    })
    return {'user_id': profile.id, 'codeforces': codeforces or '',
            'discord': discord or '', 'atcoder': atcoder or ''}


def delete_social_handle(profile):
    _mutate('social_handles', str(profile.id), None)

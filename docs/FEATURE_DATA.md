# Feature data

Disqualification reasons and the three social handles used to be columns on the
main database:

| Old column | Table | Now lives in |
| --- | --- | --- |
| `disqualify_reason` | `judge_contestparticipation` | `feature_data.json` → `disqualify` |
| `disqualify_reason_detail` | `judge_contestparticipation` | `feature_data.json` → `disqualify` |
| `codeforces_handle` | `judge_profile` | `feature_data.json` → `social_handles` |
| `discord_handle` | `judge_profile` | `feature_data.json` → `social_handles` |
| `atcoder_handle` | `judge_profile` | `feature_data.json` → `social_handles` |

They moved to a JSON file so that dropping them from the main database needs no
schema migration, and so they can be edited or restored without touching MariaDB.

## File format

One JSON object, written by `judge/feature_data/api.py`:

```json
{
  "version": 1,
  "disqualify": {
    "8": { "contest": 6, "reason": "other", "detail": "do đẹp trai" }
  },
  "social_handles": {
    "1": { "codeforces": "MieAi.", "discord": "imnotsally", "atcoder": "MieAii" }
  }
}
```

Keys are stringified ids — participation id under `disqualify`, profile id under
`social_handles`. Non-ASCII is written unescaped, so the file is readable.

## Location

`dmoj/local_settings.py`:

```python
FEATURE_DATA_PATH = '/home/oj/site/feature_data.json'
```

Defaults to `BASE_DIR/feature_data.json` if unset. A sibling `feature_data.json.lock`
file is created for `flock` and is safe to ignore.

## Behaviour that matters

- **Reads degrade, writes do not.** A missing or corrupt file makes reads return
  no data and logs a warning, so a scoreboard page still renders. A failed write
  raises `FeatureDataError` — silently dropping a reason would lose what an
  operator just typed.
- **Writes go to the file first**, then to MariaDB. The two stores cannot share a
  transaction, so if the MariaDB write fails the leftover is an orphan reason
  next to an unflagged participation, which is harmless. The reverse — a flagged
  participation with a vanished reason — is not.
- **Concurrency is handled.** Every mutation takes an exclusive `flock` and is
  published with `os.replace` from a temp file in the same directory, which is
  atomic on POSIX. A reader never observes a half-written file, and concurrent
  writers cannot lose each other's entries.
- **The file is world-readable (0644)** so the web, celery and bridged processes
  can all read it. The service processes run as `oj`, so the file *directory*
  must be writable by `oj` for disqualify reasons and profile edits to save.

## Editing by hand

Stop the writers, edit, then start them again — a hand edit racing a process
write is lost:

```bash
supervisorctl stop bridged site celery
$EDITOR /home/oj/site/feature_data.json
supervisorctl start site celery bridged
```

Verify afterwards:

```python
from judge.feature_data.api import get_disqualify_reasons, get_social_handle
get_disqualify_reasons([8, 9, 11])
get_social_handle(1)
```

## Tests

`judge/tests/test_feature_data.py` points `FEATURE_DATA_PATH` at a temp file, so
it never touches the production store. It covers the missing/corrupt/partial-file
paths, unicode, id stringification, concurrent writes, and the two integration
points (scoreboard rows and the profile form):

```bash
/home/oj/vnojsite/bin/python manage.py test judge.tests.test_feature_data
```

## Note on the judge

`Problem.storage` / `Judge.storages` are unrelated to this file: they are part of
upstream's storage-backends work and live in the main database. The judge must
speak protocol v2 and announce its storages, which means a `judge_version: 2`
config whose `problem_storage_globs` entries carry both an `id` and a `glob`:

```yaml
id: myjudge
judge_version: 2
problem_storage_globs:
  - id: local
    glob: /problems/*
```

A bare `- /problems/*` string is the v1 form and raises at judge startup. A
missing `judge_version` leaves `Judge.storages` empty and nothing judgeable;
`Problem.usable_languages` is the quickest end-to-end check for that.

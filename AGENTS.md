# AGENTS.md

VNOJ — a Vietnamese DMOJ/DMOJ-site fork (Django 4.2). Live site is served by
nginx → uwsgi → Django, with celery and the judge bridge as sibling processes.

## Layout

- `judge/` — the actual application: models (`judge/models/*.py`), views, forms,
  templates context, bridge (`judge/bridge/`), tasks, migrations, tests.
- `dmoj/` — settings only. `dmoj/settings.py` `exec()`s `dmoj/local_settings.py`
  at the **end** of the file, so anything set there wins. `local_settings.py` is
  gitignored and machine-specific (MariaDB creds, `FEATURE_DATA_PATH`,
  `LANGUAGE_CODE='vi'`, `VNOJ_*` overrides).
- `resources/` — scss/js sources; `templates/` — Django templates;
  `locale/` — translations; `urlshortener/`, `django_ace/`, `martor/` — apps.
- `docs/FEATURE_DATA.md` — read it before touching disqualify reasons or social
  handles; they now live in a JSON file, **not** the database.
- Two sibling checkouts outside this repo matter: `/home/oj/judge-server` (the
  judge, `dmoj` package) and `/home/oj/problem_data/` (problem storage root).

## Commands

Use the venv at `/home/oj/vnojsite`; `manage.py` alone will use system python.

```bash
/home/oj/vnojsite/bin/python manage.py test judge urlshortener --noinput
/home/oj/vnojsite/bin/python manage.py test judge.tests.test_feature_data
/home/oj/vnojsite/bin/python manage.py migrate
/home/oj/vnojsite/bin/python manage.py runserver 0.0.0.0:8000   # dev only
./make_style.sh                                                 # sass + postcss
npx prettier --check websocket                                 # only JS linted
supervisorctl restart site bridged celery                      # after code changes
```

`--noinput` matters for `manage.py test`: stale `test_dmoj_*` databases exist and
Django otherwise blocks on a prompt.

flake8 (CI's lint job) is **not** installed in the venv. Reproduce CI with
`pip install "setuptools<82" flake8 flake8-import-order flake8-future-import
flake8-commas flake8-logging-format flake8-quotes` then `flake8`. Config is
`.flake8` (max line 120, pycharm import order, `local_settings.py` excluded).

## Gotchas an agent would otherwise hit

- **19 of 22 existing test failures are environmental, not bugs.** With
  `LANGUAGE_CODE='vi'` every assertion on translated English text fails
  (`urlshortener.tests.test_views`, `judge.models.tests.test_problem`), and
  `VNOJ_ENABLE_SYNC_API=False` means `api/v2/sync/*` URLs are not registered at
  all, so all of `judge/tests/test_api_sync.py` gets 404. Both suites pass with
  `LANGUAGE_CODE='en', VNOJ_ENABLE_SYNC_API=True`. Do not "fix" the
  locale-dependent tests to match production. The 3 real errors in
  `judge/tests/test_judge_list.py` (a stale 6-arg `JudgeList.judge()` call) were
  fixed; that suite now passes.
- **Never change `/home/oj/judge-server`.** It is a separate checkout we have no
  permission to modify, so only the site may adapt to it. In particular, do not
  add or expect new packet keys; the site has to work with what the judge
  already sends.
- **`DjangoHandler.on_submission` must not require `storage`.** The internal
  `submission-request` packet goes to the site's *own* `DjangoHandler` on
  `BRIDGED_DJANGO_ADDRESS` (9998), not to a judge, and `judgeapi.judge_submission`
  does not send `storage`. Reading it as `data['storage']` raised
  `KeyError: 'storage'` on every submission in `/home/oj/tmp/bridge.stderr.log`
  and marked IE. The handler now uses `data.get('storage')` and
  `JudgeList.judge()` falls back to `StorageManager.get_instance().default_name`
  when it is empty. Do not "fix" this by putting `storage` back in the packet.
- **`storages__contains` needs MariaDB.** `Problem.usable_languages` and
  `judge/views/problem.py` filter on the judge's `storages` JSONField, which
  Django refuses on sqlite (`supports_json_field_contains` is False), so the
  sqlite default in `dmoj/settings.py` 500s those pages.
- **The `storage-namespace` key is never sent.** `judge_handler.on_handshake`
  keeps only the storage *ids*, and `submission-request` omits
  `storage-namespace`, so the judge always resolves its default namespace. That
  is correct for the single-namespace `traubo.yml` but will misroute the moment
  a second `storage_namespaces:` entry is added to the judge config.
- **CSS is versioned by hand, and `/static` is NOT `resources/`.** Two separate
  traps, both of which make a correct-looking stylesheet change a no-op:
  1. `make_style.sh` writes `resources/style.css` and `resources/dark/style.css`
     (both gitignored), but the site actually serves whatever `DMOJ_THEME_CSS` in
     `dmoj/settings.py` names. To ship a style change: build, then
     `cp resources/style.css resources/style.v42.css` and the same under
     `resources/dark/`, then bump `DMOJ_THEME_CSS`. `resources/dark/` is
     gitignored, so only the light copy is committed — the dark one must be
     created on disk.
  2. nginx serves `location /static` from `root /home/oj` (see
     `/etc/nginx/conf.d/nginx.conf`), so `/static/x` resolves to
     `/home/oj/static/x` — a **copy** of `resources/`, not a symlink and not the
     same directory. `STATICFILES_DIRS` pointing at `resources/` is irrelevant;
     nothing auto-syncs. After building you must also
     `cp resources/<file>.css /home/oj/static/` (and `/home/oj/static/dark/`) or
     the site keeps serving the stale bytes. The copies have been observed
     drifting by days, and `style.css` can be stale too, not just per-page CSS.

  Always verify over HTTP before claiming a style change shipped:
  `curl -s http://localhost/static/<file>.css | grep -c '<new-selector>'`.
  A DOM assertion (element count, `hero: 0`) proves only that the *template*
  changed and says nothing about the CSS. To check layout actually moved, measure
  it — see the `CKTOJ_SHOW_HOME_HERO` note below.
- **Hiding a block from the home grid needs an explicit class, not `:has()`.**
  `.home-layout` is a CSS grid where `.home-main`/`.home-sidebar` are
  `display: contents`, so the hero is pinned `grid-row: 1 / 3` to align its bottom
  with the contests widget. Removing the hero leaves grid rows 1–2 empty and pushes
  `.home-section` (`grid-row: 3`) down, producing a large dead gap. The fix is a
  conditional class on `.home-layout` plus a `.home-layout--no-hero` rule that
  moves `.home-section` to `grid-row: 1 / 3`. Keep the state in the template, which
  already knows the flag, rather than inferring it with `:has()`.
  `judge/tests/test_cktoj_toggles.py` asserts the class tracks the setting —
  extend it if you add another layout toggle. To confirm the gap is actually gone,
  measure `.home-section`'s `getBoundingClientRect().top` in a headless browser: it
  should be ~84px (level with the sidebar user card), not ~448px.
- **Migrations have parallel branches.** `judge/migrations/` contains duplicate
  numbers and many `*_merge_*` files. Run `makemigrations judge` and let Django
  generate the merge rather than hand-numbering. Commits 30658560/50b2cce2 added
  then deleted 0242–0245, so anything you remember about them is wrong.
- **The judge must speak protocol v2.** `judge/bridge/judge_handler.py` rejects
  `version: 1` handshakes, and the handshake's `storages` list is what
  `Problem.usable_languages` filters on. A judge config needs
  `judge_version: 2` and `problem_storage_globs` entries as `{id, glob}` dicts;
  the bare `- /problems/*` string form raises at judge startup. The active judge
  runs in the `traubo` docker container using `/home/oj/problem_data/traubo.yml`.
- **`runbridged` no longer takes `--monitor` / `--problem-storage-globs`.**
  `judge/bridge/monitor.py` was deleted; `judge_daemon()` takes no arguments.
- **Submodules are required**: `resources/libs` (site-assets) and `resources/vnoj`
  (vnoj-static). `resources/vnoj` currently has an untracked `comicneue/` dir —
  do not commit it into the submodule.
- `dmoj/settings.py` defaults to sqlite and `DEBUG=True`; MariaDB and the real
  debug flag come only from `local_settings.py`. Never commit changes to it.

## Conventions

- Feature data (disqualify reasons, codeforces/discord/atcoder handles) is
  written **file-first, then DB**, under `flock` + `os.replace`. Reads degrade to
  empty on a corrupt file; writes raise `FeatureDataError`. Do not make reads
  raise.
- Commit messages in this fork are often Vietnamese and free-form
  (`vibe coded by @…`, `ai biet sua gi`). Match that rather than inventing
  conventional subjects.
- Default branch is `master`; active work happens on `new-ui`.

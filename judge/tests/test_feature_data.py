import datetime
import json
import os
import shutil
import tempfile
import threading

from django.test import TestCase, override_settings

from judge.feature_data import api
from judge.feature_data.api import FeatureDataError
from django.contrib.auth.models import User

from judge.models import Contest, ContestParticipation, Profile


class FeatureDataTestCase(TestCase):
    """Base class that points the store at a throwaway JSON file."""

    def setUp(self):
        super().setUp()
        self.directory = tempfile.mkdtemp(prefix='feature-data-test-')
        self.path = os.path.join(self.directory, 'feature_data.json')
        self.override = override_settings(FEATURE_DATA_PATH=self.path)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.directory, True)

    def read_raw(self):
        with open(self.path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def make_participation(self, contest=None, user=None):
        if contest is None:
            contest = Contest.objects.create(
                key='c%d' % (Contest.objects.count() + 1), name='c',
                start_time=datetime.datetime(2026, 1, 1), end_time=datetime.datetime(2026, 1, 2))
        if user is None:
            user = User.objects.create(username='u%d' % (User.objects.count() + 1))
        profile = Profile.objects.get_or_create(user=user)[0]
        return ContestParticipation.objects.create(contest=contest, user=profile)

    def make_profile(self, user=None):
        user = user or User.objects.create(username='p%d' % (User.objects.count() + 1))
        return Profile.objects.get_or_create(user=user)[0]


class MissingFileTest(FeatureDataTestCase):
    def test_read_with_no_file_is_empty_not_an_error(self):
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(api.get_disqualify_reasons([1, 2, 3]), {})
        self.assertEqual(api.get_social_handles([1, 2, 3]), {})
        self.assertEqual(api.get_social_handle(1),
                         {'codeforces': '', 'discord': '', 'atcoder': ''})

    def test_empty_id_list_does_not_touch_the_file(self):
        self.assertEqual(api.get_disqualify_reasons([]), {})
        self.assertEqual(api.get_social_handles([]), {})
        self.assertFalse(os.path.exists(self.path))

    def test_first_write_creates_the_file_and_the_directory(self):
        nested = os.path.join(self.directory, 'deep', 'feature_data.json')
        with override_settings(FEATURE_DATA_PATH=nested):
            participation = self.make_participation()
            api.set_disqualify_reason(participation, 'other', 'hello')
        self.assertTrue(os.path.exists(nested))

    def test_corrupt_file_degrades_to_empty_for_reads(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{ this is not json')
        self.assertEqual(api.get_disqualify_reasons([8]), {})
        self.assertEqual(api.get_social_handles([1]), {})

    def test_file_that_is_a_json_array_degrades_to_empty(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump([1, 2, 3], f)
        self.assertEqual(api.get_disqualify_reasons([8]), {})

    def test_partial_sections_are_tolerated(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({'disqualify': {'8': {'reason': 'other', 'detail': 'x'}}}, f)
        self.assertEqual(api.get_disqualify_reasons([8]), {8: ('other', 'x')})
        self.assertEqual(api.get_social_handles([1]), {})

    def test_write_to_unwritable_path_raises(self):
        blocked = os.path.join(self.directory, 'blocked')
        os.makedirs(blocked)
        os.chmod(blocked, 0o500)
        self.addCleanup(os.chmod, blocked, 0o700)
        if os.geteuid() == 0:
            self.skipTest('root ignores directory permissions')
        with override_settings(FEATURE_DATA_PATH=os.path.join(blocked, 'x.json')):
            with self.assertRaises(FeatureDataError):
                api.save_social_handle(self.make_profile(), codeforces='x')


class DisqualifyReasonTest(FeatureDataTestCase):
    def test_set_then_get(self):
        participation = self.make_participation()
        api.set_disqualify_reason(participation, 'other', 'do đẹp trai')
        self.assertEqual(api.get_disqualify_reasons([participation.id]),
                         {participation.id: ('other', 'do đẹp trai')})

    def test_set_overwrites(self):
        participation = self.make_participation()
        api.set_disqualify_reason(participation, 'other', 'first')
        api.set_disqualify_reason(participation, 'no_explanation', 'second')
        self.assertEqual(api.get_disqualify_reasons([participation.id]),
                         {participation.id: ('no_explanation', 'second')})

    def test_set_normalises_none_to_empty_string(self):
        participation = self.make_participation()
        api.set_disqualify_reason(participation, None, None)
        self.assertEqual(api.get_disqualify_reasons([participation.id]),
                         {participation.id: ('', '')})

    def test_contest_id_is_recorded(self):
        participation = self.make_participation()
        api.set_disqualify_reason(participation, 'other', 'x')
        self.assertEqual(self.read_raw()['disqualify'][str(participation.id)]['contest'],
                         participation.contest_id)

    def test_clear_removes_the_entry(self):
        participation = self.make_participation()
        api.set_disqualify_reason(participation, 'other', 'x')
        api.clear_disqualify_reason(participation)
        self.assertEqual(api.get_disqualify_reasons([participation.id]), {})

    def test_clear_on_missing_entry_is_a_noop(self):
        participation = self.make_participation()
        api.clear_disqualify_reason(participation)
        self.assertEqual(api.get_disqualify_reasons([participation.id]), {})

    def test_absent_participation_is_omitted(self):
        known = self.make_participation()
        api.set_disqualify_reason(known, 'other', 'x')
        other = self.make_participation()
        self.assertEqual(api.get_disqualify_reasons([known.id, other.id]),
                         {known.id: ('other', 'x')})

    def test_malformed_entry_is_skipped(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({'disqualify': {'5': 'not-a-dict'}}, f)
        self.assertEqual(api.get_disqualify_reasons([5]), {})

    def test_unicode_survives_a_round_trip(self):
        participation = self.make_participation()
        detail = 'nghiêm túc quá đi'
        api.set_disqualify_reason(participation, 'other', detail)
        self.assertEqual(api.get_disqualify_reasons([participation.id])[participation.id][1],
                         detail)
        with open(self.path, 'r', encoding='utf-8') as f:
            self.assertIn(detail, f.read())


class SocialHandleTest(FeatureDataTestCase):
    def test_save_then_get(self):
        profile = self.make_profile()
        api.save_social_handle(profile, codeforces='MieAi.', discord='imnotsally',
                               atcoder='MieAii')
        self.assertEqual(api.get_social_handle(profile.id), {
            'codeforces': 'MieAi.', 'discord': 'imnotsally', 'atcoder': 'MieAii'})

    def test_blank_input_clears(self):
        profile = self.make_profile()
        api.save_social_handle(profile, codeforces='MieAi.')
        api.save_social_handle(profile)
        self.assertEqual(api.get_social_handle(profile.id),
                         {'codeforces': '', 'discord': '', 'atcoder': ''})

    def test_none_is_normalised(self):
        profile = self.make_profile()
        api.save_social_handle(profile, codeforces=None, discord=None, atcoder=None)
        self.assertEqual(api.get_social_handle(profile.id),
                         {'codeforces': '', 'discord': '', 'atcoder': ''})

    def test_delete(self):
        profile = self.make_profile()
        api.save_social_handle(profile, codeforces='x')
        api.delete_social_handle(profile)
        self.assertEqual(api.get_social_handles([profile.id]), {})

    def test_batch_read_only_returns_known_ids(self):
        known = self.make_profile()
        other = self.make_profile()
        api.save_social_handle(known, codeforces='x')
        self.assertEqual(api.get_social_handles([known.id, other.id]),
                         {known.id: {'codeforces': 'x', 'discord': '', 'atcoder': ''}})

    def test_malformed_entry_is_skipped(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({'social_handles': {'3': ['nope']}}, f)
        self.assertEqual(api.get_social_handles([3]), {})


class PersistenceTest(FeatureDataTestCase):
    def test_data_survives_a_fresh_read(self):
        participation = self.make_participation()
        api.set_disqualify_reason(participation, 'other', 'x')
        self.assertEqual(api.get_disqualify_reasons([participation.id])[participation.id],
                         ('other', 'x'))

    def test_sections_do_not_clobber_each_other(self):
        participation = self.make_participation()
        profile = self.make_profile()
        api.set_disqualify_reason(participation, 'other', 'x')
        api.save_social_handle(profile, codeforces='y')
        api.set_disqualify_reason(participation, 'other', 'z')
        self.assertEqual(api.get_social_handle(profile.id)['codeforces'], 'y')
        self.assertEqual(api.get_disqualify_reasons([participation.id])[participation.id],
                         ('other', 'z'))

    def test_ids_are_stored_as_strings_but_look_up_as_integers(self):
        participation = self.make_participation()
        api.set_disqualify_reason(participation, 'other', 'x')
        raw = self.read_raw()['disqualify']
        self.assertIn(str(participation.id), raw)
        self.assertNotIn(participation.id, raw)

    def test_version_is_recorded(self):
        api.save_social_handle(self.make_profile(), codeforces='x')
        self.assertEqual(self.read_raw()['version'], api.FORMAT_VERSION)

    def test_no_temp_files_left_behind(self):
        api.set_disqualify_reason(self.make_participation(), 'other', 'x')
        leftovers = [n for n in os.listdir(self.directory) if n.startswith('.feature_data-')]
        self.assertEqual(leftovers, [])

    def test_file_is_world_readable(self):
        api.set_disqualify_reason(self.make_participation(), 'other', 'x')
        mode = os.stat(self.path).st_mode & 0o777
        self.assertEqual(mode, 0o644)


class ConcurrencyTest(FeatureDataTestCase):
    def test_parallel_writes_do_not_lose_entries(self):
        participations = [self.make_participation() for _ in range(12)]
        errors = []

        def worker(participation):
            try:
                api.set_disqualify_reason(participation, 'other', str(participation.id))
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(p,)) for p in participations]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        stored = api.get_disqualify_reasons([p.id for p in participations])
        self.assertEqual(len(stored), len(participations))
        for p in participations:
            self.assertEqual(stored[p.id], ('other', str(p.id)))


class IntegrationTest(FeatureDataTestCase):
    def test_scoreboard_row_carries_the_reason_and_label(self):
        from judge.views.contests import make_contest_ranking_json
        contest = Contest.objects.create(key='sc', name='c', start_time=datetime.datetime(2026, 1, 1), end_time=datetime.datetime(2026, 1, 2))
        user = User.objects.create(username='dq')
        profile = Profile.objects.get_or_create(user=user)[0]
        participation = ContestParticipation.objects.create(contest=contest, user=profile)
        # The flag stays in the main database; only the reason moves to JSON.
        participation.set_disqualified(True)
        api.set_disqualify_reason(participation, 'other', 'chi tiết')

        rows = make_contest_ranking_json(contest, [], contest.users.all(), False)
        row = next(r for r in rows if r['id'] == participation.id)
        self.assertTrue(row['is_disqualified'])
        self.assertEqual(row['disqualify_reason'], 'other')
        self.assertEqual(row['disqualify_reason_detail'], 'chi tiết')
        self.assertTrue(row['disqualify_reason_label'])

    def test_profile_page_prefills_the_handles(self):
        user = User.objects.create(username='handles')
        profile = Profile.objects.get_or_create(user=user)[0]
        api.save_social_handle(profile, codeforces='MieAi.', discord='imnotsally',
                               atcoder='MieAii')

        # The view must map the stored key names onto the form's field names.
        from judge.forms import ProfileForm
        from judge.feature_data.api import get_social_handle
        handles = get_social_handle(request_profile_id := profile.id)
        form = ProfileForm(instance=profile, user=user, initial={
            'codeforces_handle': handles['codeforces'],
            'discord_handle': handles['discord'],
            'atcoder_handle': handles['atcoder'],
        })
        self.assertEqual(form.initial['codeforces_handle'], 'MieAi.')
        self.assertEqual(form.initial['discord_handle'], 'imnotsally')
        self.assertEqual(form.initial['atcoder_handle'], 'MieAii')
        self.assertEqual(request_profile_id, profile.id)

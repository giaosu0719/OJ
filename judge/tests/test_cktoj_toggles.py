from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from judge.models import Organization, Profile


class CKTOJToggleTestCase(TestCase):
    def setUp(self):
        user = User.objects.create_superuser('cktoj_toggle_admin', 'a@example.com', 'password')
        Profile.objects.create(user=user)
        self.client = Client()
        self.client.login(username='cktoj_toggle_admin', password='password')

    def assertPage(self, url, needle, present):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(needle in response.content.decode(), present, '%s in %s' % (needle, url))

    def test_badge_column_toggle(self):
        for url in (reverse('user_list'), reverse('contributors_list')):
            with self.settings(CKTOJ_SHOW_BADGE_COLUMN=False):
                self.assertPage(url, 'badge-col', False)
            with self.settings(CKTOJ_SHOW_BADGE_COLUMN=True):
                self.assertPage(url, 'badge-col', True)

    def test_badge_column_toggle_organization(self):
        Organization.objects.create(name='cktoj-toggle-org', slug='cktoj-toggle-org')
        url = reverse('organization_users', kwargs={'slug': 'cktoj-toggle-org'})
        with self.settings(CKTOJ_SHOW_BADGE_COLUMN=False):
            self.assertPage(url, 'badge-col', False)
        with self.settings(CKTOJ_SHOW_BADGE_COLUMN=True):
            self.assertPage(url, 'badge-col', True)

    def test_home_hero_toggle(self):
        with self.settings(CKTOJ_SHOW_HOME_HERO=False):
            self.assertPage(reverse('home'), 'home-hero', False)
        with self.settings(CKTOJ_SHOW_HOME_HERO=True):
            self.assertPage(reverse('home'), 'home-hero', True)

    def test_home_hero_layout_class(self):
        # The CSS that collapses the empty grid rows keys off this class,
        # so it must track the setting or the gap comes back.
        with self.settings(CKTOJ_SHOW_HOME_HERO=False):
            self.assertPage(reverse('home'), 'home-layout--no-hero', True)
        with self.settings(CKTOJ_SHOW_HOME_HERO=True):
            self.assertPage(reverse('home'), 'home-layout--no-hero', False)

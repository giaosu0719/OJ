from collections import defaultdict

from django.conf import settings
from django.db.models import Count, F, FilteredRelation, Max, Q
from django.utils import timezone

from judge.models import BlogPost, Comment, Contest, ContestParticipation, Language, Problem, Profile, Submission
from judge.views import TitledTemplateView


def get_top_rated_users():
    return (Profile.objects.filter(rating__isnull=False, is_unlisted=False)
            .order_by('-rating')
            .only('user', 'rating', 'display_rank', 'display_badge', 'username_display_override')
            .select_related('user', 'display_badge')
            [:settings.VNOJ_HOMEPAGE_TOP_USERS_COUNT])


def get_top_contributors():
    return (Profile.objects.order_by('-contribution_points')
            .filter(contribution_points__gt=0, is_unlisted=False)
            .only('user', 'contribution_points', 'display_rank', 'display_badge', 'rating',
                  'username_display_override')
            .select_related('user', 'display_badge')
            [:settings.VNOJ_HOMEPAGE_TOP_USERS_COUNT])


def get_top_tbc_users():
    return (Profile.objects
            .annotate(tbc_badges=FilteredRelation('badges',
                                                  condition=Q(badges__name__regex=r'^TBC[0-9]')))
            .filter(is_unlisted=False, tbc_badges__name__isnull=False)
            .annotate(badge_count=Count('tbc_badges'))
            .order_by('-badge_count', F('rating').desc(nulls_last=True))
            .only('user', 'rating', 'display_rank', 'display_badge',
                  'username_display_override')
            .select_related('user', 'display_badge')
            [:settings.VNOJ_HOMEPAGE_TOP_USERS_COUNT])


def get_user_champ_count(profile):
    pattern = r'^TBC[0-9]'
    contest_ids = list(
        Contest.objects.filter(Q(name__regex=pattern) | Q(key__regex=pattern))
                       .values_list('id', flat=True)
    )
    if not contest_ids:
        return 0

    participations = (ContestParticipation.objects
                      .filter(contest_id__in=contest_ids, virtual=ContestParticipation.LIVE)
                      .exclude(is_disqualified=True)
                      .annotate(submission_count=Count('submission'))
                      .values('contest_id', 'user_id', 'score', 'cumtime', 'tiebreaker', 'submission_count'))

    by_contest = defaultdict(list)
    for part in participations:
        by_contest[part['contest_id']].append(part)

    def rank_key(part):
        return (-part['score'], part['cumtime'], part['tiebreaker'], -part['submission_count'])

    count = 0
    for parts in by_contest.values():
        best = min(parts, key=rank_key)
        best_key = rank_key(best)
        if any(part['user_id'] == profile.id and rank_key(part) == best_key for part in parts):
            count += 1
    return count


def build_home_widgets_context(user, profile=None):
    now = timezone.now()
    visible_contests = Contest.get_visible_contests(user) \
                              .filter(is_visible=True).order_by('start_time')

    current_contests = visible_contests.filter(start_time__lte=now, end_time__gt=now)
    future_contests = visible_contests.filter(start_time__gt=now)

    home_contests = [(contest, True) for contest in current_contests]
    home_contests += [(contest, False) for contest in future_contests]
    home_contests = home_contests[:3]
    home_contests += [None] * (3 - len(home_contests))

    context = {
        'home_contests': home_contests,
        'top_rated_users': get_top_rated_users(),
        'top_contrib': get_top_contributors(),
        'top_tbc_users': get_top_tbc_users(),
        'home_top_users_count': settings.VNOJ_HOMEPAGE_TOP_USERS_COUNT,
        'comments': Comment.most_recent(user, 10),
    }

    if profile is not None:
        if profile.rating is not None:
            context['user_rating_rank'] = Profile.objects.filter(
                is_unlisted=False, rating__gt=profile.rating,
            ).count() + 1
        context['user_solved_count'] = profile.problem_count
        context['user_submissions_count'] = profile.submission_set.count()
        context['user_champ_count'] = get_user_champ_count(profile)

    return context


class HomeView(TitledTemplateView):
    template_name = 'home.html'
    title = 'Home'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        now = timezone.now()

        posts = (BlogPost.objects.filter(visible=True, publish_on__lte=now,
                                         organization=None, global_post=True)
                                 .order_by('-sticky', '-publish_on')
                                 .prefetch_related('authors__user', 'authors__display_badge')
                                 [:8])
        context['posts'] = posts
        context['post_comment_counts'] = {
            int(page[2:]): count for page, count in
            Comment.objects.filter(page__in=['b:%d' % post.id for post in posts], hidden=False)
                           .values_list('page').annotate(count=Count('page')).order_by()
        }

        profile = None
        if self.request.user.is_authenticated:
            profile = getattr(self.request, 'profile', None)
        context.update(build_home_widgets_context(self.request.user, profile))

        context['new_problems'] = Problem.get_public_problems() \
                                         .order_by('-date', 'code')[:settings.DMOJ_BLOG_NEW_PROBLEM_COUNT]

        context['user_count'] = Profile.objects.count()
        context['problem_count'] = Problem.get_public_problems().count()
        context['submission_count'] = Submission.objects.aggregate(max_id=Max('id'))['max_id'] or 0
        context['language_count'] = Language.objects.count()

        return context
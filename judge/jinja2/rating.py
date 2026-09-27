from judge.ratings import rating_class, rating_name, rating_progress
from judge.utils.external_rating import get_codeforces_class, get_atcoder_class
from . import registry


def _get_rating_value(func, obj):
    if obj is None:
        return None

    if isinstance(obj, int):
        return func(obj)
    else:
        return func(obj.rating)


@registry.function(name='rating_class')
def get_rating_class(obj):
    return _get_rating_value(rating_class, obj) or 'rate-none'


@registry.function(name='rating_name')
def get_name(obj):
    return _get_rating_value(rating_name, obj) or 'Unrated'


@registry.function(name='rating_progress')
def get_progress(obj):
    return _get_rating_value(rating_progress, obj) or 0.0


@registry.function(name='cf_rating_class')
def get_cf_rating_class(handle):
    return get_codeforces_class(handle)


@registry.function(name='ac_rating_class')
def get_ac_rating_class(handle):
    return get_atcoder_class(handle)


@registry.function(name='social_handles')
def get_social_handles(user):
    """External handles for a profile, read from the feature-data file.

    Returns a dict with 'codeforces', 'discord' and 'atcoder' keys so the
    template can use one lookup instead of three model attributes that no
    longer exist on Profile.
    """
    if user is None:
        return {'codeforces': '', 'discord': '', 'atcoder': ''}
    from judge.feature_data.api import get_social_handle
    return get_social_handle(user.id)


@registry.function
@registry.render_with('user/rating.html')
def rating_number(obj):
    return {'rating': obj}

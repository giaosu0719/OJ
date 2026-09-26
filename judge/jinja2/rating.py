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


@registry.function
@registry.render_with('user/rating.html')
def rating_number(obj):
    return {'rating': obj}

import requests
from django.core.cache import cache
from django.conf import settings
from judge.ratings import rating_class

_TIMEOUT = getattr(settings, 'OJ_REQUESTS_TIMEOUT', 10)
CACHE_DURATION = 3600 * 6  # 6 hours

def get_codeforces_rating(handle):
    if not handle:
        return None
    cache_key = f'cf_rating_{handle}'
    rating = cache.get(cache_key)
    if rating is not None:
        return rating if rating != -1 else None

    try:
        url = f'https://codeforces.com/api/user.info?handles={handle}'
        response = requests.get(url, timeout=_TIMEOUT)
        data = response.json()
        if data['status'] == 'OK':
            rating = data['result'][0].get('rating')
            if rating is not None:
                cache.set(cache_key, rating, CACHE_DURATION)
                return rating
    except Exception:
        pass
    
    # Cache -1 for failure to avoid spamming
    cache.set(cache_key, -1, 300)
    return None

def get_atcoder_rating(handle):
    if not handle:
        return None
    cache_key = f'ac_rating_{handle}'
    rating = cache.get(cache_key)
    if rating is not None:
        return rating if rating != -1 else None

    try:
        # Using history/json which is relatively stable
        url = f'https://atcoder.jp/users/{handle}/history/json'
        response = requests.get(url, timeout=_TIMEOUT)
        data = response.json()
        if data:
            rating = data[-1].get('NewRating')
            if rating is not None:
                cache.set(cache_key, rating, CACHE_DURATION)
                return rating
    except Exception:
        pass

    # Cache -1 for failure to avoid spamming
    cache.set(cache_key, -1, 300)
    return None

def get_codeforces_class(handle):
    rating = get_codeforces_rating(handle)
    if rating is None:
        return 'rate-none'
    return rating_class(rating)

def get_atcoder_class(handle):
    rating = get_atcoder_rating(handle)
    if rating is None:
        return 'atcoder-none'
    
    if rating < 400: return 'atcoder-gray'
    if rating < 800: return 'atcoder-brown'
    if rating < 1200: return 'atcoder-green'
    if rating < 1600: return 'atcoder-cyan'
    if rating < 2000: return 'atcoder-blue'
    if rating < 2400: return 'atcoder-yellow'
    if rating < 2800: return 'atcoder-orange'
    return 'atcoder-red'

# quiz/templatetags/custom_tags.py

from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    # [수정] 안전장치 추가: 딕셔너리가 아니면 None 반환 (에러 방지)
    if not dictionary or not hasattr(dictionary, 'get'):
        return None
    return dictionary.get(key)
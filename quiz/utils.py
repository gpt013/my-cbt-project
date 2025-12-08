from django.db.models import Count, Q
from .models import UserAnswer, Tag

def calculate_tag_stats(user):
    """
    특정 유저의 문제 풀이 데이터를 기반으로 태그별 정답률을 분석합니다.
    Return: [
        {'tag': '안전 수칙', 'total': 10, 'correct': 9, 'rate': 90},
        {'tag': '회로 이론', 'total': 5, 'correct': 1, 'rate': 20},
        ...
    ]
    """
    # 1. 사용자가 푼 모든 답변 조회
    user_answers = UserAnswer.objects.filter(test_result__user=user)
    
    # 2. 태그별 통계 집계
    tag_stats = {}
    
    for answer in user_answers:
        # 문제에 연결된 태그들 가져오기
        tags = answer.question.tags.all()
        
        for tag in tags:
            if tag.name not in tag_stats:
                tag_stats[tag.name] = {'total': 0, 'correct': 0}
            
            tag_stats[tag.name]['total'] += 1
            if answer.is_correct:
                tag_stats[tag.name]['correct'] += 1
    
    # 3. 리스트 변환 및 정답률 계산
    result_list = []
    for tag_name, data in tag_stats.items():
        rate = int((data['correct'] / data['total']) * 100) if data['total'] > 0 else 0
        result_list.append({
            'tag': tag_name,
            'total': data['total'],
            'correct': data['correct'],
            'rate': rate
        })
    
    # 정답률 낮은 순(약점) -> 높은 순(강점) 정렬
    result_list.sort(key=lambda x: x['rate'])
    
    return result_list
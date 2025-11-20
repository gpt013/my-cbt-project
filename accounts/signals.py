from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User, Group
from .models import Profile

@receiver(post_save, sender=Profile)
def auto_assign_user_to_groups(sender, instance, created, **kwargs):
    """
    프로필이 저장될 때, '기수(Cohort)', '공정(Process)', '회사(Company)'에 맞는 
    그룹을 자동으로 생성하고 사용자를 해당 그룹에 소속시킵니다.
    """
    user = instance.user
    profile = instance

    # --- 1. 기존에 자동으로 생성된 그룹은 모두 제거 (정보 변경 시 그룹 이동을 위해) ---
    # '기수:', '공정:', '팀:', '회사:' 로 시작하는 그룹만 타겟으로 합니다.
    auto_group_prefixes = ['기수:', '공정:', '팀:', '회사:']
    
    # 사용자가 속한 그룹 중 자동 생성 그룹만 필터링하여 제거
    groups_to_remove = []
    for group in user.groups.all():
        for prefix in auto_group_prefixes:
            if group.name.startswith(prefix):
                groups_to_remove.append(group)
                break
    
    if groups_to_remove:
        user.groups.remove(*groups_to_remove)
    
    # --- 2. 새로운 정보에 맞춰 그룹 생성 및 추가 ---
    groups_to_add = []
    
    # [수정] 기수 그룹 (예: "기수: 25-01기")
    # profile.cohort는 객체이므로 .name으로 접근합니다.
    if profile.cohort:
        group_name = f"기수: {profile.cohort.name}"
        group, _ = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)

    # [수정] 공정 그룹 (예: "공정: CMP")
    # profile.process는 객체이므로 .name으로 접근합니다.
    if profile.process:
        group_name = f"공정: {profile.process.name}"
        group, _ = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)
        
    # [수정] 기수-공정 연합 팀 그룹 (예: "팀: 25-01기-CMP")
    if profile.cohort and profile.process:
        group_name = f"팀: {profile.cohort.name}-{profile.process.name}"
        group, _ = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)
    
    # [수정] 회사 그룹 (예: "회사: 삼성전자")
    # profile.company는 객체이므로 .name으로 접근합니다.
    if profile.company:
        group_name = f"회사: {profile.company.name}"
        group, _ = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)
        
    # 찾거나 생성한 모든 그룹에 사용자를 한 번에 추가합니다.
    if groups_to_add:
        user.groups.add(*groups_to_add)
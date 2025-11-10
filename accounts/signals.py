from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User, Group
from .models import Profile

@receiver(post_save, sender=Profile)
def auto_assign_user_to_groups(sender, instance, created, **kwargs):
    """
    프로필이 저장될 때, '기수', '공정', '회사'에 맞는 그룹을 자동으로 생성하고
    사용자를 해당 그룹에 소속시킵니다.
    """
    user = instance.user
    profile = instance

    # --- 1. 기존에 자동으로 생성된 그룹은 모두 제거 (상태 변경 대비) ---
    # [수정] '회사:'를 자동 제거 접두어에 추가합니다.
    auto_group_prefixes = ['기수:', '공정:', '팀:', '회사:']
    for group in user.groups.all():
        for prefix in auto_group_prefixes:
            if group.name.startswith(prefix):
                user.groups.remove(group)
                break
    
    groups_to_add = []
    
    # 기수 그룹 (예: "기수: 30")
    if profile.class_number:
        group_name = f"기수: {profile.class_number}"
        group, created = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)

    # 공정 그룹 (예: "공정: ETCH_TAS")
    if profile.process:
        group_name = f"공정: {profile.process}"
        group, created = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)
        
    # 기수-공정 그룹 (예: "팀: 30-ETCH_TAS")
    if profile.class_number and profile.process:
        group_name = f"팀: {profile.class_number}-{profile.process}"
        group, created = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)
    
    # --- [핵심 추가] 회사 그룹 (예: "회사: 삼성전자") ---
    if profile.company:
        group_name = f"회사: {profile.company.name}"
        group, created = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)
    # ---------------------------------------------
        
    # 찾거나 생성한 모든 그룹에 사용자를 한 번에 추가합니다.
    if groups_to_add:
        user.groups.add(*groups_to_add)

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User, Group
from django.contrib.auth.signals import user_logged_in  # ★ [추가됨] 로그인 감지용 부품
from .models import Profile

# =====================================================================
# 1. [기존 로직] 프로필 저장 시 그룹 자동 할당
# =====================================================================
@receiver(post_save, sender=Profile)
def auto_assign_user_to_groups(sender, instance, created, **kwargs):
    """
    프로필이 저장될 때, '기수(Cohort)', '공정(Process)', '회사(Company)'에 맞는 
    그룹을 자동으로 생성하고 사용자를 해당 그룹에 소속시킵니다.
    """
    user = instance.user
    profile = instance

    # --- 1. 기존에 자동으로 생성된 그룹은 모두 제거 (정보 변경 시 그룹 이동을 위해) ---
    auto_group_prefixes = ['기수:', '공정:', '팀:', '회사:']
    
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
    
    if profile.cohort:
        group_name = f"기수: {profile.cohort.name}"
        group, _ = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)

    if profile.process:
        group_name = f"공정: {profile.process.name}"
        group, _ = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)
        
    if profile.cohort and profile.process:
        group_name = f"팀: {profile.cohort.name}-{profile.process.name}"
        group, _ = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)
    
    if profile.company:
        group_name = f"회사: {profile.company.name}"
        group, _ = Group.objects.get_or_create(name=group_name)
        groups_to_add.append(group)
        
    if groups_to_add:
        user.groups.add(*groups_to_add)

# =====================================================================
# 2. ★ [신규 로직] 중복 로그인 방지를 위한 '최신 접속증' 기록
# =====================================================================
@receiver(user_logged_in)
def update_session_key(sender, user, request, **kwargs):
    """로그인 시 현재 발급받은 '최신 접속증 번호'를 프로필에 적어둡니다."""
    
    # 아직 접속증(세션)이 안 만들어졌다면 생성
    if not request.session.session_key:
        request.session.create() 
        
    # 내 프로필에 현재 발급받은 최신 접속증 번호를 도장 쾅! 찍어둠
    if hasattr(user, 'profile'):
        user.profile.session_key = request.session.session_key
        user.profile.save()
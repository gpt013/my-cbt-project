# accounts/views.py
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import render, redirect

def signup(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False) # DB에 바로 저장하지 않고
            user.is_active = False         # is_active를 False로 설정
            user.save()                    # 그 후에 저장
            # 회원가입 성공 후 로그인 페이지로 이동합니다.
            # (로그인은 아직 구현 전이지만 미리 연결해둡니다.)
            return redirect('/accounts/login/') 
    else:
        form = UserCreationForm()
    return render(request, 'accounts/signup.html', {'form': form})
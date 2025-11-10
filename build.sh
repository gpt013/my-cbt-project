#!/usr/bin/env bash
# exit on error
set -o errexit

# 1. 필요한 라이브러리 설치
pip install -r requirements.txt

# 2. 정적 파일(CSS/JS) 수집
python manage.py collectstatic --noinput

# 3. 데이터베이스 스키마 적용
python manage.py migrate

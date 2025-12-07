# attendance/utils.py

import cv2
import numpy as np
import pytesseract
from PIL import Image
from datetime import datetime
import re
import os

# [배포 시 주의] Render 등 리눅스 서버에서는 tesseract가 설치되어 있어야 함.
# 윈도우 로컬 테스트용 경로 (필요시 주석 해제)
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def analyze_mdm_image(image_path):
    """
    이미지 경로를 받아 1) 시간 유효성, 2) 보안 위반(파란색) 여부를 판단
    리턴: (is_valid_time, detected_time, is_security_violation)
    """
    
    # 1. 이미지 로드 (OpenCV)
    img = cv2.imread(image_path)
    if img is None:
        return False, None, True # 읽기 실패는 위반으로 간주

    # --- A. 색상 분석 (보안 위반 감지) ---
    # BGR -> HSV 변환
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # 파란색 범위 설정 (일반적인 MDM 해제 화면의 파란색)
    lower_blue = np.array([100, 50, 50])
    upper_blue = np.array([130, 255, 255])
    
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    blue_pixels = cv2.countNonZero(mask)
    total_pixels = img.shape[0] * img.shape[1]
    
    # 전체 화면의 30% 이상이 파란색이면 위반으로 간주
    is_security_violation = (blue_pixels / total_pixels) > 0.3

    # --- B. OCR 시간 분석 ---
    try:
        pil_img = Image.open(image_path)
        text = pytesseract.image_to_string(pil_img)
        
        # 날짜/시간 패턴 찾기 (YYYY-MM-DD HH:MM:SS 등 다양한 포맷)
        # 예: 2025-11-25 17:40
        match = re.search(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})\s+(\d{1,2}):(\d{2})', text)
        
        detected_time = None
        is_valid_time = False
        
        if match:
            date_str = f"{match.group(1)}-{match.group(2)}-{match.group(3)} {match.group(4)}:{match.group(5)}"
            detected_time = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            
            # 현재 시간과 비교 (5분 이내 허용)
            now = datetime.now()
            diff = abs((now - detected_time).total_seconds())
            
            if diff <= 300: # 300초 = 5분
                is_valid_time = True
                
    except Exception as e:
        print(f"OCR Error: {e}")
        return False, None, True # 에러 시 안전하게 실패 처리

    return is_valid_time, detected_time, is_security_violation
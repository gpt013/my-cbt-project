try:
    # base.html 파일을 읽기 모드('r')로 열어봅니다.
    with open('templates/base.html', 'r', encoding='utf-8') as f:
        print("성공! base.html 파일을 읽었습니다.")
        # print(f.read()) # 파일 내용 전체 출력 (선택 사항)
except Exception as e:
    print("--- 실패! 파일을 읽는 중 오류가 발생했습니다. ---")
    print(e)
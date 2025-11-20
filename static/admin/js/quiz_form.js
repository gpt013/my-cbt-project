document.addEventListener('DOMContentLoaded', function() {
    // ==========================================
    // 1. 문제 출제 방식에 따른 필드 숨김/표시
    // ==========================================
    const methodSelect = document.querySelector('#id_generation_method');
    const examSheetRow = document.querySelector('.field-exam_sheet');
    const tagsRow = document.querySelector('.field-required_tags');

    function toggleMethodFields() {
        const value = methodSelect.value;
        
        // 초기화 (일단 다 숨김)
        if(examSheetRow) examSheetRow.style.display = 'none';
        if(tagsRow) tagsRow.style.display = 'none';

        if (value === '지정') {
            // '지정 문제 세트' 선택 시
            if(examSheetRow) examSheetRow.style.display = 'block';
        } else if (value === '태그') {
            // '태그 조합 랜덤' 선택 시
            if(tagsRow) tagsRow.style.display = 'block';
        }
        // '랜덤'일 때는 둘 다 숨김 상태 유지
    }

    if (methodSelect) {
        methodSelect.addEventListener('change', toggleMethodFields);
        toggleMethodFields(); // 페이지 로드 시 1회 실행
    }

    // ==========================================
    // 2. 응시 권한 설정 (그룹/개인) 토글 버튼 생성
    // ==========================================
    const groupRow = document.querySelector('.field-allowed_groups');
    const userRow = document.querySelector('.field-allowed_users');
    
    // 토글 버튼을 넣을 위치 (응시 권한 섹션 헤더 아래 또는 첫 번째 필드 위)
    // Django Admin의 fieldset 구조상 groupRow 바로 위에 삽입합니다.
    if (groupRow && userRow) {
        const toggleContainer = document.createElement('div');
        toggleContainer.style.padding = '10px 0 20px 10px';
        toggleContainer.style.borderBottom = '1px solid #eee';
        toggleContainer.style.marginBottom = '10px';
        
        toggleContainer.innerHTML = `
            <label style="margin-right: 15px; font-weight: bold;">응시 대상 선택:</label>
            <label style="margin-right: 10px; cursor: pointer;">
                <input type="radio" name="access_toggle" value="group" checked> 그룹(기수/공정) 단위
            </label>
            <label style="margin-right: 10px; cursor: pointer;">
                <input type="radio" name="access_toggle" value="user"> 개별 인원 지정
            </label>
            <label style="margin-right: 10px; cursor: pointer;">
                <input type="radio" name="access_toggle" value="both"> 둘 다 사용
            </label>
        `;

        // 그룹 필드 바로 앞에 컨트롤러 삽입
        groupRow.parentNode.insertBefore(toggleContainer, groupRow);

        const radios = document.getElementsByName('access_toggle');

        function toggleAccessFields() {
            let selectedValue = 'group';
            for (const radio of radios) {
                if (radio.checked) {
                    selectedValue = radio.value;
                    break;
                }
            }

            if (selectedValue === 'group') {
                groupRow.style.display = 'block';
                userRow.style.display = 'none';
            } else if (selectedValue === 'user') {
                groupRow.style.display = 'none';
                userRow.style.display = 'block';
            } else {
                groupRow.style.display = 'block';
                userRow.style.display = 'block';
            }
        }

        // 라디오 버튼 이벤트 연결
        radios.forEach(radio => {
            radio.addEventListener('change', toggleAccessFields);
        });

        // 초기 상태 설정 (값이 이미 들어있는 쪽을 우선으로 보여줌)
        // (개별 인원에 값이 있고 그룹이 비어있으면 '개별'로 자동 선택 등)
        // 여기서는 편의상 기본값 'group'으로 시작하되, 저장된 데이터가 있으면 로직 추가 가능
        toggleAccessFields();
    }
});
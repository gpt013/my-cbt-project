// static/admin/js/quiz_admin.js (최종 수정본)

window.addEventListener("load", function() {
    (function($) {
        $(document).ready(function() {
            const methodSelect = $('#id_generation_method');
            const sheetSelectRow = $('.field-exam_sheet');

            function toggleSheetSelect() {
                // --- [핵심 수정] 'FIXED'가 아닌, 실제 값인 '지정'을 확인합니다 ---
                if (methodSelect.val() === '지정') {
                    sheetSelectRow.show();
                } else {
                    sheetSelectRow.hide();
                }
            }
            
            methodSelect.on('change', toggleSheetSelect);
            toggleSheetSelect(); // 페이지 로드 시 실행
        });
    })(django.jQuery);
});
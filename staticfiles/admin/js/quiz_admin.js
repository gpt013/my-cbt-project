window.addEventListener("load", function() {
    (function($) {
        $(document).ready(function() {
            
            // 1. '문제 출제 방식'에 따른 '문제 세트' 필드 표시 로직 (기존 기능)
            const methodSelect = $('#id_generation_method');
            const sheetSelectRow = $('.field-exam_sheet');

            function toggleSheetSelect() {
                if (methodSelect.val() === '지정') {
                    sheetSelectRow.show();
                } else {
                    sheetSelectRow.hide();
                }
            }
            
            methodSelect.on('change', toggleSheetSelect);
            toggleSheetSelect(); // 페이지 로드 시 실행

            // 2. [새 기능] '퀴즈 분류'에 따른 '관련 공정' 필드 표시 로직
            const categorySelect = $('#id_category');
            const processRow = $('.field-associated_process');

            function toggleProcessField() {
                if (categorySelect.val() === '공정') {
                    processRow.show();
                } else {
                    processRow.hide();
                    // '공통'을 선택하면 '관련 공정' 필드를 깨끗하게 비웁니다.
                    $('#id_associated_process').val(''); 
                }
            }

            categorySelect.on('change', toggleProcessField);
            toggleProcessField(); // 페이지 로드 시 실행

        });
    })(django.jQuery);
});
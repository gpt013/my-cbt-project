// static/admin/js/process_handler.js

// Django admin 페이지의 jQuery를 안전하게 사용하기 위한 설정
window.addEventListener("load", function() {
    (function($) {
        $(document).ready(function() {
            // '공정' 필드와 그 필드가 속한 행(row)을 찾습니다.
            const processRow = $('#id_profile-0-process').closest('.form-row');

            // 체크박스를 담을 새로운 행(row)을 만듭니다.
            const checkboxHtml = `
                <div class="form-row field-etch_options" style="display: none;">
                    <div>
                        <label>ETCH 상세 공정:</label>
                        <div class="related-widget-wrapper">
                            <input type="checkbox" id="id_etch_tas" style="margin-left: 10px;"> <label for="id_etch_tas">TAS</label>
                            <input type="checkbox" id="id_etch_lam" style="margin-left: 20px;"> <label for="id_etch_lam">LAM</label>
                        </div>
                    </div>
                </div>
            `;
            processRow.after(checkboxHtml);

            const etchOptionsRow = $('.field-etch_options');
            const processInput = $('#id_profile-0-process');
            const tasCheckbox = $('#id_etch_tas');
            const lamCheckbox = $('#id_etch_lam');

            // '공정' 필드에 글자를 입력할 때마다 실행될 함수
            processInput.on('input', function() {
                if ($(this).val().toUpperCase().includes('ETCH')) {
                    etchOptionsRow.show(); // 'ETCH'가 포함되면 체크박스를 보여줌
                } else {
                    etchOptionsRow.hide(); // 아니면 숨김
                }
            });

            // TAS 체크박스를 클릭했을 때
            tasCheckbox.on('change', function() {
                if ($(this).is(':checked')) {
                    processInput.val('ETCH_TAS');
                    lamCheckbox.prop('checked', false); // LAM은 체크 해제
                } else {
                    processInput.val('ETCH');
                }
            });

            // LAM 체크박스를 클릭했을 때
            lamCheckbox.on('change', function() {
                if ($(this).is(':checked')) {
                    processInput.val('ETCH_LAM');
                    tasCheckbox.prop('checked', false); // TAS는 체크 해제
                } else {
                    processInput.val('ETCH');
                }
            });

            // 페이지 로드 시에도 한 번 실행
            processInput.trigger('input');
        });
    })(django.jQuery);
});
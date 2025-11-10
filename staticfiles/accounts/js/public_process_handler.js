// static/accounts/js/public_process_handler.js

document.addEventListener('DOMContentLoaded', function() {
    const processInput = document.getElementById('id_process');
    const etchOptionsRow = document.getElementById('etch_options_row');
    const tasCheckbox = document.getElementById('id_etch_tas');
    const lamCheckbox = document.getElementById('id_etch_lam');

    // '공정' 필드에 글자를 입력할 때마다 실행될 함수
    processInput.addEventListener('input', function() {
        if (this.value.toUpperCase().includes('ETCH')) {
            etchOptionsRow.style.display = 'block'; // 'ETCH'가 포함되면 체크박스를 보여줌
        } else {
            etchOptionsRow.style.display = 'none'; // 아니면 숨김
        }
    });

    tasCheckbox.addEventListener('change', function() {
        if (this.checked) {
            processInput.value = 'ETCH_TAS';
            lamCheckbox.checked = false;
        } else {
            processInput.value = 'ETCH';
        }
    });

    lamCheckbox.addEventListener('change', function() {
        if (this.checked) {
            processInput.value = 'ETCH_LAM';
            tasCheckbox.checked = false;
        } else {
            processInput.value = 'ETCH';
        }
    });

    // 페이지 로드 시에도 한 번 실행
    processInput.dispatchEvent(new Event('input'));
});
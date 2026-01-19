// ==================== ПРОСТО РАБОЧИЙ JWT ФРОНТ ====================
// Вставляй вместо всего твоего main.js
console.log("🔥🔥🔥 DEBUG MAIN JS — SHOULD BE VISIBLE 🔥🔥🔥");
const API_BASE = '';

function setToken(token) { localStorage.setItem('jwt', token); }
function getToken() { return localStorage.getItem('jwt'); }
function removeToken() { localStorage.removeItem('jwt'); }

async function login(username, password) {
    const resp = await fetch('/api/token/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
    });
    const data = await resp.json();
    if (resp.ok) {
        setToken(data.access);
        updateLoginButton();
        alert('Успешно вошли!');
    } else {
        alert('Ошибка входа: ' + (data.detail || 'неверные данные'));
    }
}

function logout() {
    removeToken();
    updateLoginButton();
    alert('Вы вышли');
}

function updateLoginButton() {
    const btns = document.querySelectorAll('.auth-buttons');
    const html = getToken()
        ? `<button onclick="logout()" class="auth-btn">Выйти</button>`
        : `<button onclick="promptLogin()" class="auth-btn login-btn">Войти</button>`;
    btns.forEach(b => b.innerHTML = html);
}

function promptLogin() {
    const u = prompt('Логин:');
    if (!u) return;
    const p = prompt('Пароль:');
    if (p) login(u, p);
}

// Универсальный fetch с токеном
async function apiFetch(url, options = {}) {
    const token = getToken();
    if (!token) {
        promptLogin();
        return null;
    }

    options.headers = options.headers || {};
    options.headers['Authorization'] = 'Bearer ' + token;

    let resp = await fetch(url, options);

    // Если токен протух — пробуем обновить
    if (resp.status === 401) {
        const refreshResp = await fetch('/api/token/refresh/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh: localStorage.getItem('jwt_refresh') || '' })
        });
        if (refreshResp.ok) {
            const d = await refreshResp.json();
            setToken(d.access);
            options.headers['Authorization'] = 'Bearer ' + d.access;
            resp = await fetch(url, options); // повторяем запрос
        } else {
            removeToken();
            alert('Сессия истекла');
            promptLogin();
            return null;
        }
    }
    return resp;
}
// ==================== FILEPOND И КНОПКИ (РАБОЧАЯ ВЕРСИЯ) ====================

// Инициализация FilePond (это у тебя уже было — оставь как есть)
const pondDelete = FilePond.create(document.querySelector('.filepond-delete'), {
    allowMultiple: false,
    maxFileSize: '30MB',
    maxFiles: 1,
    acceptedFileTypes: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel', 'text/csv']
});

const pondChangePrice = FilePond.create(document.querySelector('.filepond-change-price'), {
    allowMultiple: false,
    maxFileSize: '30MB',
    maxFiles: 1,
    acceptedFileTypes: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel', 'text/csv']
});

const pondUpload = FilePond.create(document.querySelector('.filepond-upload'), {
    allowMultiple: true,
    maxFileSize: '30MB',
    maxFiles: 3,
    acceptedFileTypes: ['application/json']
});

// Универсальная функция загрузки
async function uploadHandler(pond, url, modeId, controllerId, messageId) {
    const files = pond.getFiles();
    const msg = document.getElementById(messageId);
    if (!files.length) return msg.textContent = 'Выберите файл!';

    msg.textContent = 'Отправляю...';
    const formData = new FormData();

    files.forEach(f => {
        const cleanName = f.filename.replace(/[^a-zA-Z0-9._-]/g, '_');
        formData.append('file', f.file, cleanName);
    });
    formData.append('mode', document.getElementById(modeId).value);
    formData.append('controller', document.getElementById(controllerId).value);

    const resp = await apiFetch(url || '/api/kaufland_main/', { method: 'POST', body: formData });
    if (!resp) return;

    if (resp.ok) {
        if (messageId === 'upload-message-delete' && formData.get('mode') === 'checker') {
            const blob = await resp.blob();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'result.xlsx';
            a.click();
            msg.textContent = 'Скачано!';
        } else {
            const json = await resp.json();
            msg.textContent = json.message || 'Готово!';
            pond.removeFiles();
        }
    } else {
        const err = await resp.json();
        console.log(err)
        msg.textContent = err.error || err.detail || err.message || 'Ошибка сервера';
    }
}

// НАВЕШИВАЕМ ОБРАБОТЧИКИ ТОЛЬКО ПОСЛЕ ТОГО, КАК FilePond создал переменные!
document.getElementById('upload-button-delete').onclick = () => uploadHandler(
    pondDelete, '/api/kaufland_main/', 'mode-select-delete', 'controller-select-delete', 'upload-message-delete'
);

document.getElementById('upload-button-change-price').onclick = () => uploadHandler(
    pondChangePrice, '/api/kaufland_main/', 'mode-select-price', 'controller-select-price', 'upload-message-change-price'
);

document.getElementById('upload-button-upload').onclick = () => uploadHandler(
    pondUpload, '/api/kaufland_main/upload_json/', 'mode-select-upload', 'controller-select-upload', 'upload-message-upload'
);

// При загрузке страницы
updateLoginButton();

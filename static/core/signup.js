document.getElementById("signupForm").addEventListener("submit", function(event) {
    event.preventDefault();  // Останавливаем отправку формы по умолчанию
    console.log("Форма отправлена, но отправка предотвращена для валидации.");  // Проверка, что форма не отправляется

    const fullName = document.getElementById("fullName");
    const email = document.getElementById("email");
    const password = document.getElementById("password");
    let isValid = true;  // Переменная для проверки правильности полей

    // Сбрасываем все фидбэки и стили перед проверкой
    document.getElementById("feedback").innerText = "";
    document.getElementById("feedback").classList.remove("error", "success");
    fullName.style.borderColor = "";
    email.style.borderColor = "";
    password.style.borderColor = "";

    // Проверка поля полного имени
    if (fullName.value.trim() === "") {
        fullName.style.borderColor = "red";  // Подсветка красной рамкой
        isValid = false;
        console.log("Ошибка: Полное имя не заполнено.");
        document.getElementById("feedback").innerText += "Full Name is required.\n";
    }

    // Проверка email с помощью регулярного выражения
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(email.value.trim())) {
        email.style.borderColor = "red";
        isValid = false;
        console.log("Ошибка: Некорректный email.");
        document.getElementById("feedback").innerText += "Invalid Email Address.\n";
    }

    // Проверка минимальной длины пароля (6 символов)
    if (password.value.trim().length < 6) {
        password.style.borderColor = "red";
        isValid = false;
        console.log("Ошибка: Пароль меньше 6 символов.");
        document.getElementById("feedback").innerText += "Password must be at least 6 characters.\n";
    }

    // Проверяем, есть ли ошибки
    if (!isValid) {
        document.getElementById("feedback").classList.add("error");
        console.log("Форма не отправлена из-за ошибок.");
    } else {
        // Показываем сообщение об успешной регистрации
        console.log("Форма валидна. Показать сообщение 'Registered successfully'.");
        document.getElementById("feedback").innerText = "Registered successfully! Redirecting you to the Sign In page...";
        document.getElementById("feedback").classList.add("success");

        // Делаем задержку в 3 секунды перед перенаправлением на страницу входа
        setTimeout(function() {
            window.location.href = "signin.html";  // Перенаправляем на страницу входа
        }, 3000);  // Задержка в 3000 миллисекунд (3 секунды)
    }
});

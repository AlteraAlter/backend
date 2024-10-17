document.getElementById("signinForm").addEventListener("submit", function(event) {
    event.preventDefault();  // Остаемся на странице

    const email = document.getElementById("email");
    const password = document.getElementById("password");
    let isValid = true;
    
    // Сбрасываем все фидбэки и стили перед проверкой
    document.getElementById("feedback").innerText = "";
    document.getElementById("feedback").classList.remove("error");
    email.style.borderColor = "";
    password.style.borderColor = "";

    // Проверка email
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(email.value.trim())) {
        email.style.borderColor = "red";
        isValid = false;
        document.getElementById("feedback").innerText += "Invalid Email Address.\n";  // Сообщение об ошибке email
    }

    // Проверка пароля
    if (password.value.trim() === "") {
        password.style.borderColor = "red";
        isValid = false;
        document.getElementById("feedback").innerText += "Password is required.\n";  // Ошибка пароля
    }

    // Вывод сообщений об ошибках
    if (!isValid) {
        document.getElementById("feedback").classList.add("error");  // Стилизуем ошибки
    } else {
        // Перенаправляем на home2.html при успешной проверке
        window.location.href = "home2.html";
    }
});

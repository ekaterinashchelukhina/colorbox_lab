// Всплывающая подсказка для ошибок с бэкенда. Роуты редиректят на исходную
// страницу с ?error=текст (utils.error_redirect) вместо отдельной страницы с одним
// <h2>Ошибка</h2> — здесь этот текст показывается поверх страницы и сам убирается
// из адресной строки, чтобы обновление страницы не показывало его повторно.
(function () {
    var params = new URLSearchParams(window.location.search);
    var message = params.get("error");
    if (!message) return;

    var toast = document.createElement("div");
    toast.textContent = message;
    toast.setAttribute("role", "alert");
    toast.style.cssText = [
        "position:fixed", "left:50%", "bottom:24px", "transform:translateX(-50%) translateY(0)",
        "max-width:min(90vw,420px)", "background:#c0392b", "color:#fff", "padding:14px 20px",
        "border-radius:10px", "font:600 14px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif",
        "box-shadow:0 10px 30px rgba(0,0,0,.25)", "z-index:9999", "cursor:pointer",
        "opacity:0", "transition:opacity .2s ease, transform .2s ease"
    ].join(";");
    document.body.appendChild(toast);
    requestAnimationFrame(function () {
        toast.style.opacity = "1";
    });

    function dismiss() {
        toast.style.opacity = "0";
        setTimeout(function () {
            toast.remove();
        }, 200);
    }
    toast.addEventListener("click", dismiss);
    var timer = setTimeout(dismiss, 5000);
    toast.addEventListener("mouseenter", function () { clearTimeout(timer); });

    params.delete("error");
    var qs = params.toString();
    var newUrl = window.location.pathname + (qs ? "?" + qs : "") + window.location.hash;
    window.history.replaceState({}, "", newUrl);
})();

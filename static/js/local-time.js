// Переводит время из UTC (хранится и пишется на сервере) в часовой пояс браузера зрителя.
// Использование: <span class="local-time" data-utc="2026-08-09T13:44:00">— fallback-текст —</span>
// Атрибут data-format: "time" — только часы:минуты, "date" — только дата,
// по умолчанию ("datetime") — полная дата и время.
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".local-time").forEach(function (el) {
        var utcTime = el.getAttribute("data-utc");
        if (!utcTime) return;
        var date = new Date(utcTime + "Z");
        if (isNaN(date.getTime())) return;
        var fmt = el.getAttribute("data-format") || "datetime";
        if (fmt === "time") {
            el.textContent = date.toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'});
        } else if (fmt === "date") {
            el.textContent = date.toLocaleDateString('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric'});
        } else if (fmt === "datetime-short") {
            el.textContent = date.toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
        } else {
            el.textContent = date.toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'});
        }
    });
});

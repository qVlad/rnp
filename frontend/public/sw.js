// Минимальный service worker для PWA-валидации (TASK-LEAD-032).
// Без кэширования пока — только skipWaiting + clients.claim, чтобы
// браузер засчитал валидный SW и разрешил "Add to home screen".
// Полноценный offline-shell — следующий итерацией (workbox).

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", () => {
  // no-op placeholder, нужен чтобы Chrome засчитал SW как валидный для PWA
});

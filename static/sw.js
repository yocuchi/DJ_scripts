const CACHE_NAME = 'dj-scripts-v2';

// Solo cacheamos el shell de la app (HTML+assets estáticos)
// Las llamadas a la API siempre van a la red
const STATIC_ASSETS = ['/'];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // La API no se toca: dejamos que el navegador la gestione directamente.
  // Es importante para el audio del reproductor (/api/database/file), que usa
  // peticiones Range: si el SW las intermedia se rompe el salto en la pista y
  // la reproducción en segundo plano.
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // Las peticiones con rango (audio/vídeo) tampoco pasan por caché
  if (event.request.headers.has('range')) {
    return;
  }

  // Para el resto: red primero, caché como fallback
  event.respondWith(
    fetch(event.request)
      .then(response => {
        // cache.put() solo admite GET; además evitamos guardar respuestas opacas
        if (event.request.method === 'GET' && response.ok && response.type === 'basic') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

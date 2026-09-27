export function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  // En desarrollo no hay /sw.js: el fallback de la SPA responde index.html y el
  // navegador se queja de "unsupported MIME type text/html". El SW solo se genera
  // al compilar (vite-plugin-pwa), así que en dev lo omitimos.
  if (!import.meta.env.PROD) return;
  const hadController = Boolean(navigator.serviceWorker.controller);
  navigator.serviceWorker.register("/sw.js").catch(() => {
    /* sin SW (dev/inseguro): el push no estǭ disponible, se degrada con gracia */
  });
  if (!hadController) return;
  let reloadedOnce = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloadedOnce) return;
    reloadedOnce = true;
    window.location.reload();
  });
}
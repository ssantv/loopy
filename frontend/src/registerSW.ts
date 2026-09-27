export function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  const hadController = Boolean(navigator.serviceWorker.controller);
  navigator.serviceWorker.register("/sw.js").catch(() => {
    /* sin SW (dev/inseguro): el push no está disponible, se degrada con gracia */
  });
  if (!hadController) return;
  let reloadedOnce = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloadedOnce) return;
    reloadedOnce = true;
    window.location.reload();
  });
}
// El push necesita el service worker, y el SW solo se registra en producción
// (ver registerSW.ts). `npm run qa:build` lo lanza contra el build servido.
export const necesitaBuild = true;

export default async function run(page, ui) {
  const out = { steps: [], final: null };
  const note = (m) => out.steps.push(m);
  const api = "http://127.0.0.1:8000";

  const email = `qa_pushui_${Date.now()}@test.com`;
  const reg = await page.request.post(api + "/api/auth/register", {
    data: { email, password: "secret123", profile_type: "adult", timezone: "Europe/Madrid" },
  });
  if (reg.status() !== 201) return { error: "register status " + reg.status() };
  const token = (await reg.json()).token;
  note("usuario fresco: " + email);

  // El SW solo se registra en build (ver registerSW.ts), así que en `npm run dev` no
  // hay push posible. Ojo: no basta con mirar si existen `PushManager` y
  // `serviceWorker`, que en headless siempre están; lo que falta es el SW
  // registrado y controlando la página, y sin eso "Desuscribir" no termina.
  await page.waitForFunction(() => !!navigator.serviceWorker?.controller, null, { timeout: 8000 }).catch(() => null);
  const sinPush = await page.evaluate(() => !navigator.serviceWorker?.controller);
  if (sinPush) return { error: "push no disponible: hay que servir el build (npm run build && npm run preview), no el dev server" };

  // Rellenar antes de que la SPA termine de redirigir a /login hacía que React
  // remontara el input y lo vaciara: el envío fallaba con "Please fill out this
  // field". Se espera a que el formulario sea el que está en pantalla.
  await page.waitForSelector("input[type=email]", { timeout: 15000 });
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/contrase/i).fill("secret123");
  await page.getByRole("button", { name: /entrar|iniciar/i }).click();
  await page.waitForSelector("text=Hola", { timeout: 15000 });
  note("login ok");

  const heading = await page.waitForSelector("text=Notificaciones", { timeout: 8000 }).catch(() => null);
  if (!heading) {
    const probe = await page.evaluate(() => ({
      PushManager: "PushManager" in window,
      SW: "serviceWorker" in navigator,
      secure: window.isSecureContext,
    }));
    return { error: "sección Notificaciones no visible", probe, snapshot: await ui.snapshot() };
  }
  note("sección Notificaciones visible");

  const subBtn = await page.getByRole("button", { name: /Suscribirme/ }).count();
  note("botón Suscribirme visible=" + subBtn);

  // La sección decide qué pintar según lo que conteste `/api/push/config`, así que
  // hay que esperar a que termine de preguntar antes de mirar: si se mira antes,
  // sale "Push no configurado" solo por haber preguntado demasiado pronto.
  await page
    .waitForFunction(() => !document.body.innerText.includes("Comprobando si el servidor tiene push"), null, { timeout: 10000 })
    .catch(() => null);
  if ((await page.getByText(/VAPID/).count()) > 0) return { error: "push desactivado en servidor" };

  // simulamos la suscripción del navegador vía API (mismo flujo que pushManager.subscribe)
  const fakeSub = {
    endpoint: "https://push.invalid/ui-fake",
    p256dh: "BP2vWp_JqSZ7eGfyk8mHjF4uLDLq9u6nbPUswhWv7ekHVInF1nsQrQ4tlyGxYJ0g2CwLmHjQ",
    auth: "sBdAUTHKEYui",
  };
  const subResult = await page.request.post(api + "/api/push/subscribe", {
    headers: { Authorization: `Bearer ${token}` },
    data: fakeSub,
  });
  note("suscripción API status=" + subResult.status() + " len=" + token.length + " body=" + (await subResult.text()).slice(0, 120));

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForSelector("text=Hola", { timeout: 15000 });
  await page.waitForTimeout(1200); // refresh() de PushSection
  note("tras recargar, 'Probar' visible=" + (await page.getByRole("button", { name: /Probar notificación/ }).count()));

  const controller = await page.evaluate(() => (navigator.serviceWorker && navigator.serviceWorker.controller ? true : false));
  note("service worker controla la página=" + controller);

  if ((await page.getByRole("button", { name: /Probar notificación/ }).count()) > 0) {
    await page.getByRole("button", { name: /Probar notificación/ }).click();
    await page.waitForSelector("text=encolada", { timeout: 8000 });
    note("Probar: 'Notificación encolada' mostrada");

    await page.getByRole("button", { name: /Desuscribir/ }).click();
    await page.waitForSelector("text=Suscripción cancelada", { timeout: 8000 });
    note("Desuscribir: 'Suscripción cancelada' y vuelve 'Suscribirme'=" + (await page.getByRole("button", { name: /Suscribirme/ }).count()));
  }

  out.final = "done";
  return out;
}
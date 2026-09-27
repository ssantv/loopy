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
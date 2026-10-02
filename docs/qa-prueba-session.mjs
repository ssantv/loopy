// El service worker solo se registra en build (ver registerSW.ts), así que este
// guion necesita el build servido, no `npm run dev`. Antes de fallar con un timeout
// de 15s sin contexto, lo dice claro.
export default async function run(page, ui) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });

  // 1. Cargar la página, esperar a que el SW tome control y recargue. En la primera
  // visita el SW acaba de registrarse y aún no controla la página, así que hay que
  // darle margen antes de darlo por ausente (si no, el guion falla siempre el
  // primero y dice "sin service worker" contra el build correcto).
  await page
    .waitForFunction(() => !!navigator.serviceWorker?.controller, null, { timeout: 15000 })
    .catch(() => null);
  const sinSw = await page.evaluate(() => !navigator.serviceWorker?.controller);
  if (sinSw) return { error: "sin service worker: hay que servir el build (npm run build && npm run preview)" };
  await page.waitForTimeout(1500);

  // 2. Segunda recarga (como hace un usuario normal tras la 1a)
  await page.reload();
  await page.waitForTimeout(1500);

  // Cuenta propia por pasada: `prueba@prueba.es` la usa también qa-ratelimit, que
  // la deja bloqueada 300s, y el login de este guion fallaba por culpa ajena.
  const email = `prueba_${Date.now()}@prueba.es`;
  await page.request.post("http://127.0.0.1:8000/api/auth/register", {
    data: { email, password: "12345678", profile_type: "adult" },
  });

  const snap = await ui.snapshot();
  const emailRef = [...snap.matchAll(/@(e\d+) textbox/g)][0]?.[1];
  if (!emailRef) return { error: "login fields not found", snap };
  await ui.fill(emailRef, email);
  await page.waitForTimeout(200);

  const snap2 = await ui.snapshot();
  const pwdRef = [...snap2.matchAll(/@(e\d+) textbox/g)][1]?.[1];
  if (!pwdRef) return { error: "password field not found", snap2 };
  await ui.fill(pwdRef, "12345678");
  await page.waitForTimeout(200);

  const snap3 = await ui.snapshot();
  const entrar = snap3.match(/@(e\d+) button "ENTRAR"/)?.[1] || snap3.match(/@(e\d+) button "Entrar"/)?.[1];
  if (entrar) await ui.click(entrar);
  await page.waitForTimeout(2500);

  const home = await ui.snapshot({ full: true });
  const swInfo = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.getRegistration();
    return { controlled: !!navigator.serviceWorker.controller, sw: reg?.active?.scriptURL ?? null };
  });
  return {
    errors,
    swInfo,
    // Entrar con la cuenta recién creada debe funcionar con el SW controlando.
    entro: home.includes('heading "Hola"') || home.includes('heading "Mi día"'),
    home,
  };
}

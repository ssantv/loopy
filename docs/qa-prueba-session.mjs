// El service worker solo se registra en build (ver registerSW.ts), así que este
// guion necesita el build servido, no `npm run dev`. `npm run qa:build` lo lanza
// contra el build; contra el dev server lo dice claro en vez de dar un timeout.
export const necesitaBuild = true;

export default async function run(page, ui) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });

  // Preguntar al service worker durante el momento en que toma el control es
  // preguntar en plena recarga: el contexto de ejecución se destruye en mitad de la
  // llamada y Playwright lo cuenta como fallo del guion cuando es la propia PWA
  // arranque. Se reintenta hasta que la página se estabilice.
  const preguntar = async (fn, intentos = 20) => {
    for (let i = 0; i < intentos; i++) {
      try {
        return await page.evaluate(fn);
      } catch {
        await page.waitForLoadState("domcontentloaded").catch(() => null);
        await page.waitForTimeout(400);
      }
    }
    return null;
  };

  // 1. Cargar la página, esperar a que el SW tome control y recargue. En la primera
  // visita el SW acaba de registrarse y aún no controla la página, así que hay que
  // darle margen antes de darlo por ausente (si no, el guion falla siempre el
  // primero y dice "sin service worker" contra el build correcto).
  await page
    .waitForFunction(() => !!navigator.serviceWorker?.controller, null, { timeout: 15000 })
    .catch(() => null);
  // Deja que la página se asiente: si justo se está recargando por el arranque del
  // SW, el siguiente `evaluate` se come un "contexto destruido" sin motivo.
  await preguntar(() => document.readyState);
  const controlada = await preguntar(() => !!navigator.serviceWorker?.controller);
  if (!controlada) return { error: "sin service worker: hay que servir el build (npm run build && npm run preview)" };
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

  // Por etiqueta y no por posición: el segundo textbox puede no haber pintado y
  // `fill(undefined)` revienta con "ref desconocida: undefined".
  const ref = async (pat) => {
    for (let intento = 0; intento < 20; intento++) {
      const id = (await ui.snapshot()).match(pat)?.[1];
      if (id) return id;
      await page.waitForTimeout(250);
    }
    return null;
  };

  const emailRef = await ref(/@(e\d+) textbox "Email"/);
  if (!emailRef) return { error: "login fields not found" };
  await ui.fill(emailRef, email);
  await page.waitForTimeout(200);

  const pwdRef = await ref(/@(e\d+) textbox "Contrase\u00f1a"/);
  if (!pwdRef) return { error: "password field not found" };
  await ui.fill(pwdRef, "12345678");
  await page.waitForTimeout(200);

  const entrar = await ref(/@(e\d+) button "(ENTRAR|Entrar)"/);
  if (entrar) await ui.click(entrar);
  await page.waitForTimeout(2500);

  const home = await ui.snapshot({ full: true });
  const swInfo = await preguntar(async () => {
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

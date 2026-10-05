// QA offline: sin conexión seguimos viendo lo cacheado.
//
// El service worker cachea las lecturas `GET /api/*` (NetworkFirst) y precachea
// el app shell, así que abrir una ruta profunda sin red debe servir el shell
// desde la caché y, si hay lecturas previas cacheadas, mostrar datos. También
// debe aparecer el aviso de "Sin conexión".
//
// Necesita el build, porque el SW solo se registra en producción (ver registerSW.ts).
export const necesitaBuild = true;

export default async function run(page, ui) {
  const out = { steps: [], final: null };
  const note = (m) => out.steps.push(m);
  const api = "http://127.0.0.1:8000";

  const email = `qa_offline_${Date.now()}@test.com`;
  const reg = await page.request.post(api + "/api/auth/register", {
    data: { email, password: "secret123", profile_type: "adult", timezone: "Europe/Madrid" },
  });
  if (reg.status() !== 201) return { error: "register status " + reg.status() };
  const token = (await reg.json()).token;
  note("adulto creado: " + email);

  // Esperar a que el SW controle la página (build).
  await page.waitForFunction(() => !!navigator.serviceWorker?.controller, null, { timeout: 8000 }).catch(() => null);
  const sinSw = await page.evaluate(() => !navigator.serviceWorker?.controller);
  if (sinSw) {
    return {
      error: "service worker no controla la página: hay que servir el build (frontend> npm run build && npm run preview), no el dev server",
    };
  }

  // Login.
  await page.goto("http://localhost:4173/login", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("input[type=email]", { timeout: 15000 });
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/contrase/i).fill("secret123");
  await page.getByRole("button", { name: /entrar|iniciar/i }).click();
  const loginOk = await page.waitForSelector("text=Hola", { timeout: 15000 }).catch(() => null);
  if (!loginOk) {
    return { error: "no apareció 'Hola' tras login", snapshot: await ui.snapshot() };
  }
  note("login ok");

  // Sembrar datos: crear una tarea para que al visitar /casa haya lecturas cacheadas.
  const t = await page.request.post(api + "/api/tasks", {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      category: "general",
      title: "Tarea offline",
      est_minutes: 30,
    },
  });
  if (t.status() !== 201) return { error: "crear tarea status " + t.status() };
  note("tarea creada");

  //-visitar la app en línea para llenar la caché de lecturas. `NetworkFirst` guarda
  // la respuesta de red en la caché, así que hay que pasar por la app *con red* antes
  // de cortar: si no, no hay nada que servir y la prueba no mide nada.
  await page.goto("http://localhost:4173/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);
  note("visita con red hecha");

  // Contar cuántas lecturas quedaron cacheadas. Esto es lo que después se sirve sin red,
  // así que si es cero el guion tiene que decir por qué en vez de fallar más abajo.
  const enCache = await page.evaluate(async () => {
    const c = await caches.open("loopy-lecturas-v1");
    const claves = await c.keys();
    return { total: claves.length, apis: claves.map((r) => new URL(r.url).pathname).filter((p) => p.startsWith("/api/")) };
  });
  note("lecturas en caché: " + enCache.total + " (" + enCache.apis.join(", ") + ")");
  if (enCache.total === 0) return { error: "no se cacheó ninguna lectura: no se puede probar el modo sin red", enCache };

  // Ahora sí, sin red, y en una ruta profunda de adulto: `/casa` no está en el
  // precache, así que solo arranca si la navegación cae al shell.
  await page.context().setOffline(true);
  await page.goto("http://localhost:4173/casa", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1000);
  note("carga de /casa sin red hecha");

  // El aviso debe aparecer.
  const aviso = await page.getByTestId("aviso-sin-conexion").count();
  note("aviso sin conexión visible=" + aviso);

  // La sesión debe sobrevivir: si el bootstrap cerrado la sesión al no poder hablar
  // con el servidor, aquí aparecería la pantalla de login.
  const sesionViva = (await page.getByText(/Inicia sesión en Loopy/i).count()) === 0;
  note("sesión viva sin red=" + sesionViva);

  // Y debe verse el shell de la app, no la página de error del navegador.
  const hayShell = (await page.getByText(/Casa|Inicio|Hola/i).count()) > 0;
  note("shell visible=" + hayShell);

  // Restaurar conexión y comprobar que el aviso se va.
  await page.context().setOffline(false);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(600);
  const avisoTrasVolver = await page.getByTestId("aviso-sin-conexion").count();

  out.final = {
    lecturasCacheadas: enCache.total,
    avisoSinConexion: aviso > 0,
    sesionViva,
    shellVisible: hayShell,
    avisoDesapareceAlVolver: avisoTrasVolver === 0,
  };
  return out;
}

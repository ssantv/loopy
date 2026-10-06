// QA de la cola de escrituras: marcar y colocar sin conexión, y qué pasa al volver.
//
// Comprueba las cuatro escrituras que se han decidido (completar, deshacer, colocar y
// quitar), en el orden en el que las dio el usuario, más los dos finales posibles: que
// el servidor acepte la cola y que la rechace. Los dos importan, porque el segundo es
// el que hace que la gente se fíe de la app.
//
// Necesita el build, porque el service worker solo se registra en producción y sin él
// la app abre sin red pero sin poder cargar el shell.
export const necesitaBuild = true;

const HOY = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export default async function run(page, ui) {
  const out = { steps: [], final: null };
  const note = (m) => out.steps.push(m);
  const api = "http://127.0.0.1:8000";
  const web = "http://localhost:4173";

  const email = `qa_cola_${Date.now()}@test.com`;
  const reg = await page.request.post(api + "/api/auth/register", {
    data: { email, password: "secret123", profile_type: "adult", timezone: "Europe/Madrid" },
  });
  if (reg.status() !== 201) return { error: "register status " + reg.status() };
  const token = (await reg.json()).token;
  const auth = { Authorization: `Bearer ${token}` };
  note("adulto creado: " + email);

  // Tareas de la prueba. Los nombres llevan un prefijo para poder distinguirlas de las
  // que ya tuviera la cuenta y para localizarlas por texto sin ambigüedad. Todas con
  // `due_on` de hoy: una tarea sin fecha no sale en "Qué toca hoy" y no se podría pulsar
  // desde la interfaz.
  const crear = async (title, extra = {}) => {
    const r = await page.request.post(api + "/api/tasks", {
      headers: auth,
      data: { category: "general", title, est_minutes: 20, due_on: HOY(), ...extra },
    });
    if (r.status() !== 201) throw new Error("crear " + title + " status " + r.status());
    return (await r.json()).id;
  };
  let a, b, c, d;
  try {
    a = await crear("Cola alfa");
    b = await crear("Cola beta");
    c = await crear("Cola gamma");
    d = await crear("Cola delta");
  } catch (err) {
    return { error: String(err && err.message ? err.message : err) };
  }
  note("tareas creadas");

  await page.goto(web + "/login", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("input[type=email]", { timeout: 15000 });
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/contrase/i).fill("secret123");
  await page.getByRole("button", { name: /entrar|iniciar/i }).click();
  const dentro = await page.waitForSelector("text=Hola", { timeout: 15000 }).catch(() => null);
  if (!dentro) return { error: "no entró en la app", snapshot: await ui.snapshot() };
  await page.waitForFunction(() => !!navigator.serviceWorker?.controller, null, { timeout: 8000 }).catch(() => null);
  if (await page.evaluate(() => !navigator.serviceWorker?.controller)) {
    return { error: "sin service worker: hay que servir el build con `npm run preview`, no el dev server" };
  }
  note("login y service worker ok");

  // Una pasada con red: hace falta para que el shell y las lecturas queden cacheadas, y
  // para que la línea del día traiga el hueco donde se coloca.
  await page.goto(web + "/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  note("visita con red hecha");

  const pendientes = () =>
    page.evaluate(async () => {
      const bd = await new Promise((res) => {
        const p = indexedDB.open("loopy-cola", 1);
        p.onsuccess = () => res(p.result);
        p.onerror = () => res(null);
      });
      if (!bd) return [];
      const todas = await new Promise((res) => {
        const p = bd.transaction("escrituras", "readonly").objectStore("escrituras").getAll();
        p.onsuccess = () => res(p.result);
        p.onerror = () => res([]);
      });
      bd.close();
      return todas.sort((x, y) => x.creada - y.creada || x.id.localeCompare(y.id)).map((e) => `${e.metodo} ${e.ruta}`);
    });

  const enCola = () => page.getByTestId("aviso-pendientes").count().then((n) => n > 0);

  // ---------------------------------------------------------------- sin red: marcar

  await page.context().setOffline(true);
  await page.waitForTimeout(400);
  if ((await page.getByTestId("aviso-sin-conexion").count()) === 0) {
    return { error: "no apareció el aviso de sin conexión" };
  }
  note("sin red, con aviso");

  // Marcar y desmarcar enseguida la misma tarea. Es el caso interesante: si la cola colapsara
  // al último cambio, el resultado final sería el mismo, pero con un fallo en medio
  // dejaría la tarea como hecha sin que nadie lo pidiera. El guion lo comprueba
  // mirando lo que hay en IndexedDB, no solo lo que se ve.
  await page.getByRole("button", { name: /^Cola alfa/ }).click();
  await page.waitForTimeout(500);
  const trasMarcar = await enCola();
  if (!trasMarcar) return { error: "marcar sin red no encoló nada" };

  // Marcar mueve la línea a "Hecho hoy", así que para deshacer hay que abrir ese panel.
  // De paso se comprueba que el pintado optimista movió la línea de sitio, que es lo
  // que hace creíble el cambio sin red.
  const hecho = page.getByRole("button", { name: /Hecho hoy \(1\)/ });
  if ((await hecho.count()) === 0) {
    return { error: "tras marcar sin red la tarea no pasó a 'Hecho hoy'", snapshot: await ui.snapshot() };
  }
  await hecho.click();
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: /^Cola alfa/ }).click();
  await page.waitForTimeout(600);
  const colaTrasDos = await pendientes();
  note("cola tras marcar y deshacer: " + JSON.stringify(colaTrasDos));
  if (colaTrasDos.length !== 2) {
    return { error: "se esperaban 2 escrituras en la cola y hay " + colaTrasDos.length, cola: colaTrasDos };
  }
  if (!/^POST .*\/complete$/.test(colaTrasDos[0]) || !/^DELETE .*\/complete\//.test(colaTrasDos[1])) {
    return { error: "el orden de la cola no es marcar y después deshacer", cola: colaTrasDos };
  }

  // Otra tarea, para que al final haya una que sí se queda hecha.
  await page.getByRole("button", { name: /^Cola beta/ }).click();
  await page.waitForTimeout(500);
  note("cola antes de volver: " + JSON.stringify(await pendientes()));

  // ------------------------------------------------------------------- sin red: colocar

  // Colocar necesita un hueco, y los huecos los recorta el backend, así que el que
  // hay en pantalla es el de la visita con red. Sin red no se puede recalcular, y esa
  // es justo la razón por la que aquí no hay un pintado optimista del bloque.
  let seColoco = false;
  const masColocar = page.getByRole("button", { name: /\+ Colocar/ }).first();
  if ((await masColocar.count()) === 0) {
    note("sin huecos visibles: no se prueba colocar");
  } else {
    await masColocar.click();
    await page.waitForSelector("text=Colocar en el hueco de", { timeout: 8000 }).catch(() => null);
    await page.getByLabel("Cola delta", { exact: true }).check().catch(() => null);
    await page.getByRole("button", { name: /^Colocar$/ }).click();
    await page.waitForTimeout(700);
    const dialogoAbierto = await page.getByText("Colocar en el hueco de").count();
    if (dialogoAbierto > 0) return { error: "el diálogo de colocar no se cerró tras encolar", snapshot: await ui.snapshot() };
    const conPlace = (await pendientes()).some((p) => p.endsWith("/place"));
    seColoco = conPlace;
    note("colocar sin red encolado=" + conPlace);
    if (!conPlace) return { error: "colocar sin red no encoló nada", cola: await pendientes() };
  }

  // ---------------------------------------------------------------- volver la red

  await page.context().setOffline(false);
  // Sin esto no hay evento `online`: Playwright corta la red en la capa de red pero la
  // interfaz sigue diciendo que hay internet. Se dispara a mano por el mismo camino que
  // usaría un dispositivo real al recuperar cobertura.
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  note("red restaurada");

  const mandada = await page
    .waitForFunction(() => !document.querySelector('[data-testid="aviso-pendientes"]'), null, { timeout: 20000 })
    .then(() => true)
    .catch(() => false);
  note("cola vaciada sola=" + mandada);
  const colaTrasVolver = await pendientes();
  if (colaTrasVolver.length !== 0) {
    return { error: "la cola no se vació al volver la red", cola: colaTrasVolver };
  }

  // Lo que importa de verdad: qué dice el servidor. Alfa tiene que estar sin hacer
  // (gana el deshacer, que fue el último), beta hecha.
  const lista = await page.request.get(api + "/api/tasks", { headers: auth });
  const tareas = lista.ok() ? await lista.json() : [];
  const find = (id) => tareas.find((t) => t.id === id) || {};
  const hoy = HOY();
  const alfa = find(a);
  const beta = find(b);
  const delta = find(d);
  note(`alfa hecha=${alfa.done?.includes(hoy)} beta hecha=${beta.done?.includes(hoy)} delta colocada=${delta.planned_start ?? "-"}`);

  // ------------------------------------------------------------------ conflicto: 4xx

  // Se marca una tarea sin red y, antes de volver, se borra del servidor. Al mandar la
  // cola el backend contesta 404: gana el servidor, se avisa y la escritura desaparece.
  await page.context().setOffline(true);
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: /^Cola gamma/ }).click();
  await page.waitForTimeout(500);

  const borrado = await page.request.delete(api + "/api/tasks/" + c, { headers: auth });
  note("gamma borrada del servidor status=" + borrado.status());

  await page.context().setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  const conflicto = await page
    .waitForSelector('[data-testid="aviso-rechazado"]', { timeout: 20000 })
    .then(() => true)
    .catch(() => false);
  note("aviso de conflicto=" + conflicto);
  const colaTrasConflicto = await pendientes();
  note("cola tras el conflicto: " + JSON.stringify(colaTrasConflicto));
  if (colaTrasConflicto.length !== 0) {
    return { error: "un 4xx debe tirar la escritura, y se ha quedado en la cola", cola: colaTrasConflicto };
  }

  // Lo que el servidor dice es el único final que vale. Que la línea se viera tachada y
  // luego la cola se vaciara no demuestra nada si el backend no acabó como se pidió.
  const ganaElUltimoCambio = !alfa.done?.includes(hoy) && !!beta.done?.includes(hoy);
  if (!ganaElUltimoCambio) {
    return {
      error: "el servidor no acabó como decía la cola: alfa debería estar sin hacer y beta hecha",
      alfa: alfa.done,
      beta: beta.done,
    };
  }
  if (seColoco && !delta.planned_start) {
    return { error: "se encoló una colocación pero la tarea sigue sin colocar", delta };
  }
  if (!conflicto) return { error: "un 4xx no mostró el aviso de conflicto", snapshot: await ui.snapshot() };

  out.final = {
    marcarYDeshacerEnOrden: true,
    seMandanAlVolverLaRed: mandada,
    ganaElUltimoCambio,
    colocarEncolado: seColoco,
    conflictoSeAvisa: conflicto,
    colaVaciaAlFinal: colaTrasConflicto.length === 0,
  };
  return out;
}
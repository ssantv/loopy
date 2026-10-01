// QA del temporizador de "Mi día": cuenta atrás desde el estimate, al terminar
// guarda la sesión real y marca la tarea. Sin estimate cae a 25 min.
export default async function run(page, ui) {
  const tag = Date.now();
  const email = `qa_temp_${tag}@gmail.com`;
  const nombre = `Nico${tag}`;

  const seeded = await page.evaluate(async ({ email, nombre }) => {
    const base = "http://localhost:5173";
    const j = async (p, body, token) => {
      const res = await fetch(base + p, {
        method: body ? "POST" : "GET",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      });
      return { status: res.status, body: await res.json().catch(() => null) };
    };
    const adulto = await j("/api/auth/register", { email, password: "secreto123", profile_type: "adult" });
    await j("/api/auth/children", { display_name: nombre, pin: "4821", birth_date: "2015-05-10" }, adulto?.body?.token);
    const ent = await j("/api/auth/child-login", { display_name: nombre, pin: "4821" });
    const token = ent?.body?.token;
    const hoy = new Date();
    const d = (n) => new Date(hoy.getTime() + n * 864e5).toISOString().slice(0, 10);
    const t1 = await j("/api/tasks", { category: "colegio-deberes", title: "Mate: página 12", rec_type: "daily", est_minutes: 20 }, token);
    await j("/api/tasks", { category: "general", title: "Sacar la basura", rec_type: "daily" }, token);
    return { token, hoy: d(0), mateId: t1.body.id };
  }, { email, nombre });

  await page.goto("http://localhost:5173/nino");
  await page.getByLabel(/^¿Cómo te llamas\?/).fill(nombre);
  await page.getByLabel(/^Tu PIN/).fill("4821");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  await page.waitForTimeout(1500);

  const arbol = () => ui.snapshot({ full: true });

  // 1) El botón de empezar está y arranca en el estimate de la tarea (20 min).
  await page.getByRole("button", { name: "Empezar" }).click();
  await page.waitForTimeout(1200);
  const t1 = await arbol();
  const cuentaAtras = t1.includes("Plan: ~20 min");
  const relojCorriendo = /\b19:5\d\b/.test(t1);

  // 2) Terminar: guarda la sesión real y marca la tarea.
  await page.getByRole("button", { name: "Terminar y marcar" }).click();
  await page.waitForTimeout(2000);

  const estado = await page.evaluate(async ({ token, hoy, mateId }) => {
    const base = "http://localhost:5173";
    const cab = { Authorization: `Bearer ${token}` };
    const sesiones = await (await fetch(`${base}/api/work-sessions`, { headers: cab })).json();
    const tareas = await (await fetch(`${base}/api/tasks?date=${hoy}`, { headers: cab })).json();
    const mate = tareas.find((t) => t.id === mateId);
    return { sesiones, hecho: !!mate && mate.done.includes(hoy) };
  }, { token: seeded.token, hoy: seeded.hoy, mateId: seeded.mateId });

  const sesion = estado.sesiones[0];
  // Se terminó antes de tiempo, así que lo guardado es el real, no el plan: eso
  // es justo lo que distingue un temporizador de un checkbox.
  const sesionGuardada =
    !!sesion &&
    sesion.kind === "homework" &&
    sesion.task_id === seeded.mateId &&
    sesion.planned_seconds === 1200 &&
    sesion.actual_seconds >= 1 &&
    sesion.actual_seconds < 1200;

  // 3) El foco avanza a la siguiente, que sin estimate cae a 25 min.
  const t2 = await arbol();
  const avanza = t2.includes("Sacar la basura");
  await page.getByRole("button", { name: "Empezar" }).click();
  await page.waitForTimeout(1200);
  const t3 = await arbol();
  const porDefecto = t3.includes("Plan: ~25 min (por defecto)");

  return {
    cuentaAtras,
    relojCorriendo,
    sesionGuardada,
    hecho: estado.hecho,
    avanza,
    porDefecto,
    sesion,
  };
}

// QA del bloque "Ahora" de la principal: con lo de hoy cargado, la primera
// tarea debe salir destacada arriba y, al marcarla, el foco avanza a la
// siguiente. Crea sus propias cuentas y tareas (fechas relativas a hoy).
export default async function run(page, ui) {
  const tag = Date.now();
  const email = `qa_ahora_${tag}@gmail.com`;
  const nombre = `Luna${tag}`;

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
    const t2 = await j("/api/tasks", { category: "general", title: "Sacar la basura", rec_type: "daily" }, token);
    return { token, hoy: d(0), mateId: t1.body.id, basuraId: t2.body.id };
  }, { email, nombre });

  await page.goto("http://localhost:5173/nino");
  await page.getByLabel(/^¿Cómo te llamas\?/).fill(nombre);
  await page.getByLabel(/^Tu PIN/).fill("4821");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  await page.waitForTimeout(1500);

  const tree1 = await ui.snapshot({ full: true });
  const heroInicial = tree1.includes("Ahora") && tree1.includes("Mate: página 12");
  const minutos = tree1.includes("~20 min");
  // La carga del día dice "20 min de tareas" (Mate) más el aviso de la tarea sin
  // estimación. El texto llega partido en varios nodos del árbol, así que se
  // busca con regex en vez de con includes.
  const cargaAntes = tree1.includes("20 min de tareas") && /sin estimación/.test(tree1);

  await page.getByRole("button", { name: "Hecho", exact: true }).click();
  await page.waitForTimeout(1800);

  const mateDone = await page.evaluate(async ({ token, hoy, mateId }) => {
    const res = await fetch(`http://localhost:5173/api/tasks?date=${hoy}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const rows = await res.json();
    const mate = rows.find((r) => r.id === mateId);
    return !!mate && mate.done.includes(hoy);
  }, { token: seeded.token, hoy: seeded.hoy, mateId: seeded.mateId });

  const tree2 = await ui.snapshot({ full: true });
  const heroAvanza = tree2.includes("Ahora") && tree2.includes("Sacar la basura");
  // Marcar la tarea tiene que mover el número de la carga sin recargar: si no se
  // vuelve a pedir /day-load, la tarjeta se queda con los 20 min de una tarea ya
  // hecha. Al quedar solo "Sacar la basura", que no tiene estimación, no hay nada
  // que repartir y la tarjeta desaparece entera.
  const cargaBaja = !/20 min de tareas/.test(tree2) && !/Repartiendo el estudio/.test(tree2);

  return { heroInicial, minutos, cargaAntes, mateDone, heroAvanza, cargaBaja, cuerpo: tree2.slice(0, 700) };
}

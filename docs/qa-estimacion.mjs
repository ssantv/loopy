// QA de la corrección de estimaciones: 3 sesiones reales por encima de lo
// planeado hacen que Mi día sugiera el tiempo real, y que "Ajustar" lo aplique.
export default async function run(page, ui) {
  const tag = Date.now();
  const email = `qa_est_${tag}@gmail.com`;
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
    const t1 = await j(
      "/api/tasks",
      { category: "colegio-deberes", title: "Mates: pagina 12", rec_type: "daily", est_minutes: 20 },
      token,
    );
    const mateId = t1.body.id;

    // Tres sesiones reales de 50 min sobre 20 planeados: diferencia de sobra.
    for (let i = 0; i < 3; i++) {
      await j(
        "/api/work-sessions",
        {
          kind: "homework",
          task_id: mateId,
          planned_seconds: 20 * 60,
          actual_seconds: 50 * 60,
          completed_at: `${d(-3 + i)}T18:00:00`,
        },
        token,
      );
    }
    return { token, hoy: d(0), mateId };
  }, { email, nombre });

  await page.goto("http://localhost:5173/nino");
  await page.getByLabel(/^¿Cómo te llamas\?/).fill(nombre);
  await page.getByLabel(/^Tu PIN/).fill("4821");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  await page.waitForTimeout(2000);

  // Guarda contra la API sin reiniciar: si el endpoint no existe, el 404 lo
  // traga el catch de la tarjeta y el guion pasaría sin comprobar nada.
  const viva = await page.evaluate(async (mateId) => {
    const r = await fetch(
      `http://localhost:5173/api/work-sessions/estimate?kind=homework&task_id=${mateId}`,
      { headers: { Authorization: `Bearer ${localStorage.getItem("loopy_token")}` } },
    );
    return { status: r.status, body: await r.json().catch(() => null) };
  }, seeded.mateId);
  if (viva.status !== 200) return { error: `endpoint estimate no disponible (${viva.status})`, viva };

  const arbol = () => ui.snapshot({ full: true });

  // 1) Con 3 sesiones, la tarjeta propone el tiempo real.
  const t1 = await arbol();
  const sugerida = /Te suele llevar 50 min, no 20\./.test(t1);
  const botonAjustar = /Ajustar a 50 min/.test(t1);

  // 2) "Ajustar" aplica el valor real a la tarea.
  await page.getByRole("button", { name: "Ajustar a 50 min" }).click();
  await page.waitForTimeout(2000);
  const t2 = await arbol();
  const estimacionActualizada = /~50 min/.test(t2);
  const sugerenciaFuera = !/Ajustar a 50 min/.test(t2);

  const estado = await page.evaluate(
    async ({ token, hoy, mateId }) => {
      const cab = { Authorization: `Bearer ${token}` };
      // No hay GET /api/tasks/{id}: se lee de la lista del día.
      const tareas = await (await fetch(`http://localhost:5173/api/tasks?date=${hoy}`, { headers: cab })).json();
      const est = await (
        await fetch(
          `http://localhost:5173/api/work-sessions/estimate?kind=homework&task_id=${mateId}`,
          { headers: cab },
        )
      ).json();
      return { estMin: tareas.find((t) => t.id === mateId)?.est_minutes, ahora: est };
    },
    { token: seeded.token, hoy: seeded.hoy, mateId: seeded.mateId },
  );

  return {
    sugerida,
    botonAjustar,
    estimacionActualizada,
    sugerenciaFuera,
    estMinEnApi: estado.estMin,
    // Tras ajustar, la estimación ya encaja: el backend vuelve a callarse.
    callaTrasAjustar: estado.ahora.suggested_minutes === null,
    ahora: estado.ahora,
  };
}

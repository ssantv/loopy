// QA de la carga del día: Mi día enseña cuánto ocupa hoy y el aviso aparece
// solo cuando el plan de verdad no cabe bajo el tope.
//
// El guion no se fía de la pantalla: compara cada número con `/api/day-load`,
// que es el mismo origen de la tarjeta.
export default async function run(page, ui) {
  const tag = Date.now();
  const email = `qa_carga_${tag}@gmail.com`;
  const nombre = `Nico${tag}`;

  const hoy = new Date();
  const d = (n) => new Date(hoy.getTime() + n * 864e5).toISOString().slice(0, 10);

  const seeded = await page.evaluate(
    async ({ email, nombre, hoyISO }) => {
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
      await j(
        "/api/auth/children",
        { display_name: nombre, pin: "4821", birth_date: "2015-05-10", timezone: "UTC" },
        adulto?.body?.token,
      );
      const ent = await j("/api/auth/child-login", { display_name: nombre, pin: "4821" });
      const token = ent?.body?.token;

      // Extraescolar de hoy: debe contar como bloqueo del día.
      const diaSemana = new Date(hoyISO + "T12:00:00Z").getUTCDay();
      await j(
        "/api/extracurriculars",
        {
          name: "Natacion",
          day_of_week: (diaSemana + 6) % 7,
          start_time: "17:00",
          end_time: "18:30",
        },
        token,
      );

      await j(
        "/api/tasks",
        { category: "colegio-deberes", title: "Mates: pagina 12", est_minutes: 45, due_on: hoyISO },
        token,
      );

      const carga = await j("/api/day-load", null, token);
      return { token, hoy: hoyISO, carga };
    },
    { email, nombre, hoyISO: d(0) },
  );

  await page.goto("http://localhost:5173/nino");
  await page.getByLabel(/^¿Cómo te llamas\?/).fill(nombre);
  await page.getByLabel(/^Tu PIN/).fill("4821");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  await page.waitForTimeout(2500);

  // Guarda contra la API: si /api/day-load no existe, el catch deja la tarjeta
  // sin pintar y el guion pasaría sin comprobar nada.
  const viva = await page.evaluate(async () => {
    const r = await fetch("http://localhost:5173/api/day-load", {
      headers: { Authorization: `Bearer ${localStorage.getItem("loopy_token")}` },
    });
    return { status: r.status, body: await r.json().catch(() => null) };
  });
  if (viva.status !== 200) return { error: `endpoint day-load no disponible (${viva.status})`, viva };

  const arbol = () => ui.snapshot({ full: true });
  const api = viva.body;

  const t1 = await arbol();

  // 1) La línea de carga existe y suma tareas + extraescolar (45 + 90).
  // Ojo: el rótulo va en overline, así que el árbol de accesibilidad lo da en
  // mayúsculas, y los minutos viajan en nodos sueltos ("1 h 30 min" partido).
  const bloqueTuDia = /TU D[IÍ]A/.test(t1);
  const muestraTareas = /45 min de tareas/.test(t1);
  const muestraExtra = /1 h 30 min de extraescolar/.test(t1);
  const muestraReparto = /Repartiendo el estudio hasta/.test(t1);

  // 2) Una tarea sin estimación no se rellena con minutos inventados.
  const sinReloj = await page.evaluate(async () => {
    const token = localStorage.getItem("loopy_token");
    const hoy = new Date().toISOString().slice(0, 10);
    await fetch("http://localhost:5173/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ category: "general", title: "Sin estimar", due_on: hoy }),
    });
    const r = await fetch("http://localhost:5173/api/day-load", {
      headers: { Authorization: `Bearer ${token}` },
    });
    return r.json();
  });
  await page.reload();
  await page.waitForTimeout(2500);
  const t2 = await arbol();
  const avisaSinEstimacion = /sin estimaci[oó]n/.test(t2);

  // 3) El aviso de "no cabe" aparece cuando el reparto se queda corto.
  const apretado = await page.evaluate(async (hoy) => {
    const token = localStorage.getItem("loopy_token");
    await fetch("http://localhost:5173/api/auth/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ study_max_minutes: 15 }),
    });
    const cab = { Authorization: `Bearer ${token}` };
    const subs = await (await fetch("http://localhost:5173/api/subjects", { headers: cab })).json();
    const s = subs[0] ?? (await (
      await fetch("http://localhost:5173/api/subjects", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...cab },
        body: JSON.stringify({ name: "Mates", color: "#3366cc", prep_minutes: 240, session_minutes: 30 }),
      })
    ).json());
    // Examen mañana: con 15 min/día, la mayoría no llega a caber.
    const manana = new Date(Date.now() + 864e5).toISOString().slice(0, 10);
    await fetch("http://localhost:5173/api/exams", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...cab },
      body: JSON.stringify({ subject_id: s.id, exam_date: manana }),
    });
    const r = await fetch("http://localhost:5173/api/day-load", { headers: cab });
    return r.json();
  }, d(0));
  await page.reload();
  await page.waitForTimeout(2500);
  const t3 = await arbol();
  // El aviso se comprueba sobre el texto que se lee de verdad: el árbol de
  // accesibilidad parte la frase en varios nodos porque el número va en su
  // propio <span>, y así el número y la frase se podrían desincronizar sin que
  // nada se entere.
  const visible = await page.evaluate(() => document.body.innerText);
  const h = Math.floor(apretado.unplaced_study_minutes / 60);
  const m = apretado.unplaced_study_minutes % 60;
  const esperado = h ? (m ? `${h} h ${m} min` : `${h} h`) : `${m} min`;
  const citaElNumero =
    visible.includes(`Con el reparto actual, ${esperado} del plan no llegan a caber`) && apretado.unplaced_study_minutes > 0;

  return {
    bloqueTuDia,
    muestraTareas,
    muestraExtra,
    muestraReparto,
    // El backend no rellena lo que no sabe: una tarea sin estimación suma 0.
    sinInvencion: sinReloj.task_minutes === 45 && sinReloj.tasks_without_estimate === 1,
    avisaSinEstimacion,
    avisaNoCabe: /no llegan a caber/.test(t3),
    citaElNumero,
    unplaced: apretado.unplaced_study_minutes,
    api,
  };
}
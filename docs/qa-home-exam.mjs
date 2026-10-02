// El resumen del Home con niños reales: el saludo de niño, la lista de bolsillo de
// colegio y el estado de "nada pendiente". Se siembra su propia cuenta porque una
// cuenta fija deja de existir en cuanto se limpia la base, y el guion fallaba sin
// explicación (un 401 por un email que ya no estaba).
export default async function run(page, ui) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console: ${m.text()}`);
  });

  const tag = Date.now();
  const nombre = `Sol${tag}`;
  const sembrado = await page.evaluate(async ({ nombre }) => {
    const base = "http://localhost:5173";
    const j = async (p, body, token) => {
      const res = await fetch(base + p, {
        method: body ? "POST" : "GET",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      });
      return { status: res.status, body: await res.json().catch(() => null) };
    };
    const email = `qa_homeexam_${nombre}@gmail.com`;
    const adulto = await j("/api/auth/register", { email, password: "secreto123", profile_type: "adult" });
    const cab = await j("/api/auth/children", { display_name: nombre, pin: "4821", birth_date: "2015-05-10" }, adulto?.body?.token);
    const ent = await j("/api/auth/child-login", { display_name: nombre, pin: "4821" });
    const token = ent?.body?.token;
    // Sin datos la home sale vacía y las aserciones no prueban nada: se siembran
    // un examen (subject + exam) y un deber, que son las dos cosas que la home
    // del niño enseña. Un examen NO es una tarea: `/api/tasks` devuelve 422.
    const enDias = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);
    const mat = await j("/api/subjects", { name: "Sociales" }, token);
    const examen = await j("/api/exams", { subject_id: mat?.body?.id, exam_date: enDias(5) }, token);
    const deber = await j("/api/tasks", { category: "colegio-deberes", title: "Resumen de Lengua", rec_type: "daily", est_minutes: 15 }, token);
    return { email, nombre, hijo: cab?.status, examen: examen?.status, deber: deber?.status, token: !!token };
  }, { nombre });

  await page.goto("http://localhost:5173/nino");
  await page.getByLabel(/^¿Cómo te llamas\?/).fill(sembrado.nombre);
  await page.getByLabel(/^Tu PIN/).fill("4821");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  await page.waitForTimeout(1500);

  const home = await ui.snapshot({ full: true });
  return {
    errors,
    sembrado,
    // El niño entra por su puerta: "Qué toca hoy", no "Resumen".
    greeting: home.includes("Hola pequeño"),
    hayQueTocaHoy: home.includes("Qué toca hoy"),
    sinNadaPendiente: !home.includes("No tienes nada pendiente"),
    // El examen sembrado tiene que salir con su cuenta atrás, y el deber, en la
    // lista de bolsillo de abajo.
    examenEnProximos: home.includes("Sociales") && home.includes("Próximos exámenes"),
    deberEnListas: home.includes("Resumen de Lengua"),
  };
}

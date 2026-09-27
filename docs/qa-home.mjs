export default async function run(page, ui) {
  const tag = Date.now();
  const email = `qa_home_${tag}@gmail.com`;

  // 1) Crear cuenta + tareas vía API (mismo origen que la app)
  const seeded = await page.evaluate(async (email) => {
    const base = "http://localhost:5173";
    const j = async (p, body, token) => {
      const res = await fetch(base + p, {
        method: body ? "POST" : "GET",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: body ? JSON.stringify(body) : undefined,
      });
      return { status: res.status, body: await res.json().catch(() => null) };
    };
    const reg = await j("/api/auth/register", {
      email,
      password: "secreto123",
      profile_type: "child",
      birth_date: "2015-05-10",
      display_name: "Marte",
    });
    const token = reg?.body?.token;
    const t1 = await j("/api/tasks", { category: "colegio-deberes", title: "Mate: página 12", rec_type: "daily", est_minutes: 20 }, token);
    const t2 = await j("/api/tasks", { category: "general", title: "Sacar la basura", rec_type: "weekly_days", rec_week_mask: 9 }, token);
    const t3 = await j("/api/tasks", { category: "puntual", title: "Comprar leche", due_on: "2026-09-19" }, token);
    return { email, token, t1, t2, t3 };
  }, email);

  // 2) Login como ese usuario
  await page.goto("http://localhost:5173/login");
  await page.waitForTimeout(400);
  let snap = await ui.snapshot();
  const emailField = snap.match(/@(e\d+) textbox "Email/)?.[1];
  const passField = snap.match(/@(e\d+) textbox "Contraseña/)?.[1];
  const submit = snap.match(/@(e\d+) button "ENTRAR"/)?.[1];
  if (!emailField || !passField || !submit) return { error: "login form no encontrado", snap };
  await ui.fill(emailField, seeded.email);
  await ui.fill(passField, "secreto123");
  await ui.click(submit);
  await page.waitForTimeout(1500);

  // 3) Ver la Home "Qué toca hoy"
  const tree = await ui.snapshot({ full: true });
  return {
    seeded,
    loginOk: tree.includes("Hola pequeño"),
    hoyHeader: tree.includes("Qué toca hoy"),
    dailyTask: tree.includes("Mate: página 12"),
    weeklyTask: tree.includes("Sacar la basura"),
    punctualTask: tree.includes("Comprar leche"),
    body: tree.slice(0, 900),
  };
}
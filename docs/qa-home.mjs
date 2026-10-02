export default async function run(page, ui) {
  const tag = Date.now();
  const email = `qa_home_${tag}@gmail.com`;
  // Nombre único por pasada: es la clave de entrada del niño y con dos cuentas
  // que lo comparten el login se bloquea.
  const nombre = `Marte${tag}`;

  // 1) Crear cuenta + tareas vía API (mismo origen que la app)
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
    // La cuenta de niño la crea un adulto con un PIN; no hay registro de niño.
    const adulto = await j("/api/auth/register", { email, password: "secreto123", profile_type: "adult" });
    const cab = await j("/api/auth/children", { display_name: nombre, pin: "4821", birth_date: "2015-05-10" }, adulto?.body?.token);
    const ent = await j("/api/auth/child-login", { display_name: nombre, pin: "4821" });
    const token = ent?.body?.token;
    // Fechas relativas a hoy: con fechas fijas el guion se pudre al día siguiente.
    const hoy = new Date();
    const d = (n) => new Date(hoy.getTime() + n * 864e5).toISOString().slice(0, 10);
    // El bitmask de la app es bit 0=lunes..6=domingo, pero `getDay()` es 0=domingo.
    // Con una máscara fija ("9" = lunes+jueves) el guion solo pasaba esos dos días
    // y el resto de la semana fallaba sin que nada estuviera roto.
    const bitHoy = 1 << ((hoy.getDay() + 6) % 7);
    const t1 = await j("/api/tasks", { category: "colegio-deberes", title: "Mate: página 12", rec_type: "daily", est_minutes: 20 }, token);
    const t2 = await j("/api/tasks", { category: "general", title: "Sacar la basura", rec_type: "weekly_days", rec_week_mask: bitHoy }, token);
    const t3 = await j("/api/tasks", { category: "puntual", title: "Comprar leche", due_on: d(0) }, token);
    return { email, nombre, token, t1, t2, t3, bitHoy };
}, { email, nombre });

  // 2) El niño no tiene email: se entra por su puerta con nombre y PIN.
  await page.goto("http://localhost:5173/nino");
  await page.getByLabel(/^¿Cómo te llamas\?/).fill(nombre);
  await page.getByLabel(/^Tu PIN/).fill("4821");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
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
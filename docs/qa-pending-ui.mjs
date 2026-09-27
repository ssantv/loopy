export default async function run(page, ui) {
  const out = { steps: [], final: null };
  const note = (m) => out.steps.push(m);
  const api = "http://127.0.0.1:8000";
  const today = new Date();
  const iso = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const sub = (n) => {
    const d = new Date(today);
    d.setDate(d.getDate() - n);
    return iso(d);
  };

  const email = `qa_pendui_${Date.now()}@test.com`;
  const reg = await page.request.post(api + "/api/auth/register", {
    data: { email, password: "secret123" },
  });
  if (reg.status() !== 201) return { error: "register " + reg.status() };
  const token = (await reg.json()).token;
  const h = { Authorization: `Bearer ${token}` };
  await page.request.post(api + "/api/tasks", {
    headers: h,
    data: { category: "puntual", title: "puntual atrasada", due_on: sub(2) },
  });
  await page.request.post(api + "/api/tasks", {
    headers: h,
    data: { category: "puntual", title: "puntual hoy", due_on: iso(today) },
  });
  await page.request.post(api + "/api/tasks", {
    headers: h,
    data: { category: "hogar", title: "tender ropa", rec_type: "daily", rec_anchor: iso(today) },
  });
  note("usuario + 3 tareas creadas");

  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/contrase/i).fill("secret123");
  await page.getByRole("button", { name: /entrar|iniciar/i }).click();
  await page.waitForSelector("text=Hola", { timeout: 15000 });

  await page.getByRole("link", { name: "Pendientes" }).click();
  await page.waitForSelector("text=Pendientes", { timeout: 10000 });
  await page.waitForTimeout(800);
  note("página Pendientes abierta");

  const atrasadas = await page.getByText("Atrasadas").count();
  const hoy = await page.getByText("Para hoy").count();
  note(`secciones: atrasadas=${atrasadas} para-hoy=${hoy}`);
  if (atrasadas !== 1 || hoy !== 1) return { error: "secciones esperadas no visibles", snapshot: await ui.snapshot() };

  const boxes = () => page.locator('input[type="checkbox"]');
  const n = await boxes().count();
  note("filas visibles=" + n);

  // selecciono las 2 primeras y completo
  await boxes().nth(0).click({ force: true });
  await boxes().nth(1).click({ force: true });
  await page.getByRole("button", { name: /Completar \(2\)/ }).click();
  await page.waitForSelector("text=al día", { timeout: 8000 });
  await page.waitForTimeout(800);
  const remaining = await boxes().count();
  note("tras completar 2, quedan=" + remaining);
  if (remaining !== 1)
    return { error: `tras completar 2 quedan ${remaining} filas`, snapshot: await ui.snapshot() };

  // "Todas" selecciona la restante y completa
  await page.getByRole("button", { name: "Todas" }).click();
  await page.getByRole("button", { name: /Completar \(1\)/ }).click();
  await page.waitForSelector("text=No tienes nada pendiente", { timeout: 8000 });
  note("estado vacío tras completar todo");

  out.final = "done";
  return out;
}
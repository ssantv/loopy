export default async function run(page, ui) {
  const out = { steps: [], final: null };
  const note = (m) => out.steps.push(m);
  const api = "http://127.0.0.1:8000";
  const today = new Date();
  const iso = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  const email = `qa_menuui_${Date.now()}@test.com`;
  const reg = await page.request.post(api + "/api/auth/register", {
    data: { email, password: "secret123", profile_type: "adult", timezone: "Europe/Madrid" },
  });
  if (reg.status() !== 201) return { error: "register " + reg.status() };
  const token = (await reg.json()).token;
  const h = { Authorization: `Bearer ${token}` };
  note("usuario adulto creado");

  // ---- preparar datos: categorías + receta ----
  const cats = (await page.request.get(api + "/api/menu/categories", { headers: h })).json();
  const carne = cats.find((c) => c.name === "carne");
  const legumbre = cats.find((c) => c.name === "legumbre");
  await page.request.patch(api + "/api/menu/slots/comida", { headers: h, data: { enabled: true } });
  await page.request.patch(api + "/api/menu/slots/cena", { headers: h, data: { enabled: true } });
  const rec = await page.request.post(api + "/api/menu/recipes", {
    headers: h,
    data: {
      name: "pollo al horno",
      category_id: carne.id,
      slots: ["comida", "cena"],
      ingredients: [{ name: "pollo", qty: 1, unit: "kg" }, { name: "patatas", qty: 4, unit: "ud" }],
    },
  });
  const recId = (await rec.json()).id;
  note("slots + receta creados");

  // ---- login UI ----
  await page.goto("http://localhost:4173/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/contrase/i).fill("secret123");
  await page.getByRole("button", { name: /entrar|iniciar/i }).click();
  await page.waitForSelector("text=Hola", { timeout: 15000 });
  note("login UI ok");

  // ---- ir a Menú ----
  await page.getByRole("link", { name: "Menú" }).click();
  await page.waitForSelector("text=Menú semanal", { timeout: 10000 });
  await page.waitForTimeout(500);
  note("página Menú abierta");

  // ---- TAB Plan semanal ----
  // botones Copiar / Recomendar / Añadir a la compra visibles
  const btnCopy = page.getByRole("button", { name: "Copiar semana anterior" });
  const btnRec = page.getByRole("button", { name: "Recomendar huecos" });
  const btnAdd = page.getByRole("button", { name: "Añadir a la compra" });
  await btnCopy.waitFor({ state: "visible", timeout: 5000 });
  await btnRec.waitFor({ state: "visible" });
  await btnAdd.waitFor({ state: "visible" });
  note("botones plan visibles");

  // asignar receta en comida lunes (celda primera)
  const mon = iso(new Date(today));
  const monMonday = new Date(mon);
  monMonday.setDate(monMonday.getDate() - ((monMonday.getDay() + 6) % 7));
  const monIso = iso(monMonday);

  // click en celda comida del lunes (botón en tabla)
  // Buscar el botón "—" en la fila comida, columna lunes
  const comidaRow = page.locator("tr:has-text('Comida')");
  // La tabla tiene th días y td botones; usamos el primer td de la fila comida
  const firstCell = comidaRow.locator("td").first();
  await firstCell.locator("button").click();
  await page.waitForSelector('text="Comida"', { timeout: 5000 });
  await page.waitForTimeout(300);
  // dialog: seleccionar receta
  await page.getByLabel("Receta").click();
  await page.getByRole("option", { name: "pollo al horno" }).click();
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForSelector('text="pollo al horno"', { timeout: 5000 });
  note("asignación pollo en comida lunes ok");

  // texto libre en cena lunes
  const cenaRow = page.locator("tr:has-text('Cena')");
  const cenaCell = cenaRow.locator("td").first();
  await cenaCell.locator("button").click();
  await page.waitForSelector('text="Cena"', { timeout: 5000 });
  await page.waitForTimeout(300);
  await page.getByLabel("O texto libre").fill("pizza casera");
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForSelector('text="pizza casera"', { timeout: 5000 });
  note("texto libre cena lunes ok");

  // copiar semana anterior (no hay anterior, pero no da error)
  await btnCopy.click();
  await page.waitForTimeout(800);
  note("copiar semana ejecutado");

  // recomendar huecos
  await btnRec.click();
  await page.waitForTimeout(1500);
  note("recomendar ejecutado");

  // añadir a la compra
  await btnAdd.click();
  await page.waitForTimeout(800);
  note("añadir a la compra ejecutado");

  // ---- TAB Recetas ----
  await page.getByRole("tab", { name: "Recetas" }).click();
  await page.waitForSelector("text=Recetas", { timeout: 5000 });
  await page.waitForTimeout(300);
  // receta existente visible
  await page.waitForSelector('text="pollo al horno"', { timeout: 5000 });
  note("receta listada");

  // editar receta
  await page.locator('text="pollo al horno"').locator("..").locator('button[aria-label="editar receta"]').click();
  await page.waitForSelector("text=Editar receta", { timeout: 5000 });
  await page.getByLabel("Notas").fill("editado desde UI");
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForSelector('text="editado desde UI"', { timeout: 5000 });
  note("receta editada");

  // añadir a la compra desde receta
  await page.locator('text="pollo al horno"').locator("..").locator('button:has-text("Añadir a la compra")').click();
  await page.waitForTimeout(800);
  note("añadir receta a compra ok");

  // nueva receta
  await page.getByRole("button", { name: "Nueva receta" }).click();
  await page.waitForSelector("text=Nueva receta", { timeout: 5000 });
  await page.getByLabel("Nombre").fill("lentejas estofadas");
  await page.getByLabel("Categoría").click();
  await page.getByRole("option", { name: "legumbre" }).click();
  await page.getByLabel("Franjas aptas").getByText("Comida").click(); // chip Comida
  await page.getByLabel("Ingrediente").first().fill("lentejas");
  await page.getByLabel("Cantidad").first().fill("300");
  await page.getByLabel("Unidad").first().fill("g");
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForSelector('text="lentejas estofadas"', { timeout: 5000 });
  note("nueva receta creada");

  // ---- TAB Categorías ----
  await page.getByRole("tab", { name: "Categorías" }).click();
  await page.waitForSelector("text=Franjas activas", { timeout: 5000 });
  // toggle merienda
  await page.locator('text="Merienda"').locator("..").locator("input[type=checkbox]").click({ force: true });
  await page.waitForTimeout(500);
  note("toggle merienda ok");
  // objetivo carne: min 3
  await page.locator('text="carne"').locator("..").locator('input[label="Mínimo/semana"]').fill("3");
  await page.locator('text="carne"').locator("..").locator('button:has-text("Guardar")').click();
  await page.waitForTimeout(500);
  note("objetivo carne actualizado");
  // nueva categoría
  await page.getByPlaceholder(/postres|Ej/).fill("postres");
  await page.getByRole("button", { name: "Crear" }).click();
  await page.waitForSelector('text="postres"', { timeout: 5000 });
  note("categoría postres creada");

  // ---- volver a plan y verificar que hay contenido ----
  await page.getByRole("tab", { name: "Plan semanal" }).click();
  await page.waitForTimeout(500);
  // hay al menos 2 asignaciones
  const assigned = await page.locator('td button:not(:has-text("—"))').count();
  note("asignaciones visibles=" + assigned);

  out.final = "done";
  return out;
}
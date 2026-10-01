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
  // El await del .json() faltaba: page.request devuelve una promesa, así que
  // `cats` era una promesa y `cats.find` reventaba.
  const cats = await (await page.request.get(api + "/api/menu/categories", { headers: h })).json();
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
  // 4173 es el puerto de `vite preview`; el resto de guiones usan el dev (5173).
  await page.goto("http://localhost:5173/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/contrase/i).fill("secret123");
  await page.getByRole("button", { name: /entrar|iniciar/i }).click();
  await page.waitForSelector("text=Hola", { timeout: 15000 });
  note("login UI ok");

  // ---- ir a Menú ----
  // Por URL: "Menú" es una subsección de Casa y no está enlazada desde Mi día.
  await page.goto("http://localhost:5173/menu");
  await page.locator("h4", { hasText: "Menú" }).waitFor({ timeout: 10000 });
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

  // El plan es una tabla: una fila por franja y un td por día. El primer td es
  // la etiqueta de la franja, así que el lunes es el segundo.
  const filaFranja = (franja) => page.locator("tbody tr").filter({ has: page.getByText(franja, { exact: true }) });
  const lunesDe = (franja) => filaFranja(franja).locator("td").nth(1);

  await lunesDe("Comida").locator("button").click();
  await page.waitForSelector('text="Comida"', { timeout: 5000 });
  await page.waitForTimeout(300);
  // dialog: seleccionar receta
  await page.getByLabel("Receta").click();
  await page.getByRole("option", { name: "pollo al horno" }).click();
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForSelector('text="pollo al horno"', { timeout: 5000 });
  note("asignación pollo en comida lunes ok");

  // texto libre en cena lunes
  await lunesDe("Cena").locator("button").click();
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
  // Las recetas viven en cajas agrupadas por categoría; se ancla por el botón
  // "Añadir a la compra" para no quedarse con el <div> equivocado.
  const tarjetaReceta = (nombre) =>
    page
      .locator("div")
      .filter({ has: page.getByText(nombre, { exact: true }) })
      .filter({ has: page.getByRole("button", { name: "Añadir a la compra" }) })
      .last();
  await tarjetaReceta("pollo al horno").getByRole("button", { name: "editar receta" }).click();
  await page.waitForSelector("text=Editar receta", { timeout: 5000 });
  await page.getByLabel("Notas").fill("editado desde UI");
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.getByText("editado desde UI").waitFor({ timeout: 5000 });
  note("receta editada");

  // añadir a la compra desde receta
  await tarjetaReceta("pollo al horno").getByRole("button", { name: "Añadir a la compra" }).click();
  await page.waitForTimeout(800);
  note("añadir receta a compra ok");

  // nueva receta
  await page.getByRole("button", { name: "Nueva receta" }).click();
  await page.waitForSelector("text=Nueva receta", { timeout: 5000 });
  await page.getByLabel("Nombre").fill("lentejas estofadas");
  await page.getByLabel("Categoría").click();
  await page.getByRole("option", { name: "legumbre" }).click();
  // "Franjas aptas" es un rótulo, no un <label>: las franjas son chips pulsables.
  await page.getByRole("button", { name: "Comida", exact: true }).click();
  // Los ingredientes empiezan en cero: hay que añadir una fila antes de rellenarla.
  // Y se identifican por placeholder, no por label.
  await page.getByRole("button", { name: "Añadir ingrediente" }).click();
  await page.getByPlaceholder("Ingrediente").first().fill("lentejas");
  await page.getByPlaceholder("Cantidad").first().fill("300");
  await page.getByPlaceholder("Unidad").first().fill("g");
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForSelector('text="lentejas estofadas"', { timeout: 5000 });
  note("nueva receta creada");

  // ---- TAB Categorías ----
  await page.getByRole("tab", { name: "Categorías" }).click();
  await page.getByRole("heading", { name: "Franjas activas" }).waitFor({ timeout: 5000 });

  // Los switches son Switch de MUI: role=checkbox con el nombre de la etiqueta.
  const merienda = page.getByRole("checkbox", { name: "Merienda" });
  const meriendaAntes = await merienda.isChecked();
  await merienda.click();
  await page.waitForTimeout(600);
  note("toggle merienda " + meriendaAntes + "->" + (await merienda.isChecked()));

  // Cada objetivo es una caja con el nombre, sus dos campos y su botón Guardar.
  const objetivo = (nombre) =>
    page
      .locator("div")
      .filter({ has: page.getByText(nombre, { exact: true }) })
      .filter({ has: page.getByRole("button", { name: "Guardar" }) })
      .last();
  const filaCarne = objetivo("carne");
  await filaCarne.getByLabel("Mínimo/semana").fill("3");
  await filaCarne.getByRole("button", { name: "Guardar" }).click();
  await page.waitForTimeout(600);
  note("objetivo carne min=3");

  // nueva categoría
  await page.getByPlaceholder("Ej.: postres").fill("postres");
  await page.getByRole("button", { name: "Crear" }).click();
  await page.getByText("postres", { exact: true }).waitFor({ timeout: 5000 });
  note("categoría postres creada");

  // ---- volver a plan y verificar que hay contenido ----
  await page.getByRole("tab", { name: "Plan semanal" }).click();
  await page.waitForTimeout(600);
  // asignaciones = botones cuyo texto no es el guion de hueco
  const assigned = await page
    .locator("tbody td button")
    .evaluateAll((els) => els.filter((e) => e.textContent.trim() !== "\u2014").length);
  note("asignaciones visibles=" + assigned);

  out.final = "done";
  return out;
}
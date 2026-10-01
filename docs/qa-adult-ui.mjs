export default async function run(page, ui) {
  const out = { steps: [], final: null };
  const note = (m) => out.steps.push(m);
  const base = "http://127.0.0.1:8000";

  const email = `qa_ui_${Date.now()}@test.com`;
  const reg = await page.request.post(base + "/api/auth/register", {
    data: { email, password: "secret123", profile_type: "adult", timezone: "Europe/Madrid" },
  });
  if (reg.status() !== 201) return { error: "register status " + reg.status() };
  note("usuario fresco: " + email);

  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/contrase/i).fill("secret123");
  await page.getByRole("button", { name: /entrar|iniciar/i }).click();
  await page.waitForSelector("text=Hola", { timeout: 10000 });
  note("login ok");

  // ---------- Casa ----------
  // La pestaña se llama "Casa", no "Hogar": "hogar" es la categoría de tarea.
  await page.getByRole("link", { name: "Casa", exact: true }).click();
  await page.waitForSelector("text=Nueva tarea", { timeout: 10000 });

  await page.getByLabel("Tipo").click();
  await page.getByRole("option", { name: "Cosa de hoy" }).click();
  await page.getByRole("textbox", { name: "Título de la tarea" }).fill("Recoger la mesa");
  await page.getByRole("button", { name: "Añadir", exact: true }).first().click();
  await page.waitForSelector("text=Recoger la mesa", { timeout: 8000 });
  note("casa: tarea puntual creada");
  if ((await page.getByText("Salón", { exact: true }).count()) === 0) {
    await page.getByRole("textbox", { name: "Nueva habitación" }).fill("Salón");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(900);
  }
  note("casa: habitación Salón preparada");

  // ---------- Compra ----------
  // Se va por URL: la subnavegación solo enseña las secciones de la página en
  // la que estás, así que "Compra" no está enlazada desde Casa.
  await page.goto("http://localhost:5173/compra");
  await page.locator("h4", { hasText: "Compra" }).waitFor({ timeout: 10000 });

  // recomendado: primero comprar y repetir para que aparezca sugerencia
  for (let k = 0; k < 2; k++) {
    await page.getByRole("textbox", { name: "Qué comprar…" }).fill("Leche");
    await page.getByRole("textbox", { name: "Cantidad" }).fill(String(2 + k));
    await page.getByRole("button", { name: "Añadir", exact: true }).first().click();
    await page.waitForSelector("text=Leche", { timeout: 8000 });
    await page.locator("li", { hasText: "Leche" }).getByRole("checkbox").first().click();
    await page.waitForTimeout(800);
  }
  note("compra: 2 compras de 'Leche' hechas");

  // añadir una pendiente y comprarla
  await page.getByRole("textbox", { name: "Qué comprar…" }).fill("Pan");
  await page.getByRole("textbox", { name: "Cantidad" }).fill("1");
  await page.getByRole("button", { name: "Añadir", exact: true }).first().click();
  await page.waitForSelector("li:has-text('Pan')", { timeout: 8000 });
  const recom = await page.getByText(/Recomendado/).count();
  note("compra: 'Pan' pendiente; sección Recomendado visible=" + recom);

  await page.locator("li", { hasText: "Pan" }).getByRole("checkbox").first().click();
  await page.waitForSelector("text=Compradas", { timeout: 8000 });
  note("compra: 'Pan' comprada");

  // ---------- Resumen ----------
  await page.getByRole("link", { name: "Resumen", exact: true }).click();
  await page.waitForSelector("text=recibirlo", { timeout: 10000 });

  const switchEl = page.locator("label").filter({ hasText: /^Activo$/ }).locator("input");
  const switchOn = await switchEl.isChecked();
  if (switchOn !== true) {
    await switchEl.click();
    await page.waitForTimeout(700);
  }
  note("resumen: switch estado=" + (await switchEl.isChecked()));

  await page.locator("button").filter({ hasText: /^15$/ }).click();
  await page.waitForTimeout(700);
  note("resumen: excepción toggle en día 15, chip='Sin resumen'=" + (await page.getByText(/Sin resumen/).count()));

  // hora configuración
  const time = page.getByRole("textbox", { name: /Hora/i });
  if ((await time.count()) > 0) {
    await time.fill("21:00");
    await page.waitForTimeout(700);
    note("resumen: hora cambiada a 21:00");
  }

  // ---------- Inicio ----------
  await page.getByRole("link", { name: "Mi día", exact: true }).click();
  await page.waitForTimeout(1000);
  note("inicio: 'Recoger la mesa' visible=" + (await page.getByText("Recoger la mesa").count()));

  out.final = "done";
  return out;
}
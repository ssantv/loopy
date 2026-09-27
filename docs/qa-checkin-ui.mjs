import { randomUUID } from "node:crypto";

const API = "http://127.0.0.1:8000";

export default async function run(page, ui) {
  const email = `qa_ui_${Date.now()}_${randomUUID().slice(0, 6)}@gmail.com`;
  const results = {};

  await page.goto("http://localhost:5173/registro", { waitUntil: "domcontentloaded" });

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Contraseña (mín. 8 caracteres)").fill("secreto123");
  await page.getByLabel("Tipo de cuenta").click();
  await page.getByRole("option", { name: "Niño" }).click();
  await page.getByLabel("Fecha de nacimiento (para el tono)").fill("2015-05-10");
  await page.getByRole("button", { name: "Crear cuenta" }).click();

  await page.waitForURL((u) => u.pathname === "/", { timeout: 10000 });
  await page.getByText("Qué toca hoy", { exact: true }).waitFor({ timeout: 10000 });
  results.home = "ok";
  results.greeting = await page.locator("h4").innerText();

  // Perfil niño: la barra debe tener Colegio y + Check-in
  results.childNav = await page.locator("header").innerText();

  // Creo una asignatura por API para poder hacer el "examen" del check-in
  const token = await page.evaluate(() => localStorage.getItem("loopy_token"));
  const subj = await fetch(`${API}/api/subjects`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ name: "Inglés" }),
  }).then((r) => r.json());
  results.subjectCreated = subj.name ?? subj.detail;

  // Check-in
  await page.goto("http://localhost:5173/checkin", { waitUntil: "domcontentloaded" });
  await page.getByText("¿Qué te ponen hoy?", { exact: true }).waitFor({ timeout: 10000 });
  results.toneBanner = await page.getByText("Cuando te pregunte, será:").innerText();

  // Deber
  await page.getByLabel("¿Qué deber te han puesto?").fill("Fichas de mates");
  await page.getByLabel("Asignatura").click();
  await page.getByRole("option", { name: "Inglés" }).click();
  await page.getByLabel("Minutos estimados").fill("25");
  await page.getByRole("button", { name: "Añadir otro" }).click();
  await page.getByText("Añadidos (1)", { exact: true }).waitFor({ timeout: 5000 });
  results.draftDeber = (await page.locator("header").innerText()).startsWith("Loopy") ? "draft list shows" : "?";

  // Examen
  await page.getByRole("button", { name: "Examen" }).click();
  await page.getByLabel("Asignatura").click();
  await page.getByRole("option", { name: "Inglés" }).click();
  const examDate = new Date(Date.now() + 6 * 864e5).toISOString().slice(0, 10);
  await page.getByLabel("Día del examen").fill(examDate);
  await page.getByRole("button", { name: "Añadir otro" }).click();
  await page.getByText("Añadidos (2)", { exact: true }).waitFor({ timeout: 5000 });

  // Proyecto
  await page.getByRole("button", { name: "Proyecto" }).click();
  await page.getByLabel("Nombre del proyecto").fill("Trabajo de ciencias");
  await page.getByLabel("Minutos estimados").fill("120");
  await page.getByRole("button", { name: "Añadir otro" }).click();
  await page.getByText("Añadidos (3)", { exact: true }).waitFor({ timeout: 5000 });

  // Guardar -> vuelve a Mi día y el deber aparece
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 10000 });
  await page.getByText("Fichas de mates", { exact: true }).waitFor({ timeout: 10000 });
  results.afterSave = "deber visible en Mi día";

  return results;
}
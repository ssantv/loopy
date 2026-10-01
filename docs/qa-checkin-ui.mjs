import { randomUUID } from "node:crypto";

const APP = "http://localhost:5173";
const API = "http://127.0.0.1:8000";

/** Alta de la cuenta de niño por la vía real: un adulto la crea con un PIN. */
async function crearNino(email, nombre) {
  const cab = (t) => ({
    method: "POST",
    headers: { "Content-Type": "application/json", ...(t ? { Authorization: `Bearer ${t}` } : {}) },
  });
  const adulto = await fetch(`${API}/api/auth/register`, {
    ...cab(),
    body: JSON.stringify({ email, password: "secreto123", profile_type: "adult" }),
  }).then((r) => r.json());
  await fetch(`${API}/api/auth/children`, {
    ...cab(adulto.token),
    body: JSON.stringify({ display_name: nombre, pin: "4821", birth_date: "2015-05-10" }),
  });
  return fetch(`${API}/api/auth/child-login`, {
    ...cab(),
    body: JSON.stringify({ display_name: nombre, pin: "4821" }),
  }).then((r) => r.json());
}

export default async function run(page, ui) {
  const email = `qa_ui_${Date.now()}_${randomUUID().slice(0, 6)}@gmail.com`;
  // Nombre único por pasada: con dos cuentas que comparten nombre y PIN el
  // login del niño se bloquea.
  const nombre = `Marte${randomUUID().slice(0, 6)}`;
  const nino = await crearNino(email, nombre);
  const results = { alta: nino?.user?.display_name ?? nino?.detail };

  // El niño entra por su puerta: nombre + PIN, sin email.
  await page.goto(`${APP}/nino`, { waitUntil: "domcontentloaded" });
  await page.getByLabel(/^¿Cómo te llamas\?/).fill(nombre);
  await page.getByLabel(/^Tu PIN/).fill("4821");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
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
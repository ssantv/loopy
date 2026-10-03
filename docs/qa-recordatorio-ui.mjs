import { randomUUID } from "node:crypto";

const API = "http://127.0.0.1:8000";

/**
 * El recordatorio con hora es la pieza que faltaba: `Task.notify` y `Task.due_at`
 * estaban en el modelo y la API los aceptaba, pero no había forma de activarlos
 * desde la app, así que el `kind="reminder"` solo se podía provocar a mano.
 *
 * Se prueba el viaje entero: crear la tarea por la UI, activar el aviso, y
 * comprobar en la API que lo que se envió es lo que el scheduler va a leer.
 */
export default async function run(page, ui) {
  const out = {};
  const email = `qa_rec_${Date.now()}_${randomUUID().slice(0, 6)}@gmail.com`;

  const reg = await page.request.post(`${API}/api/auth/register`, {
    data: { email, password: "secret123", profile_type: "adult", timezone: "Europe/Madrid" },
  });
  if (reg.status() !== 201) return { error: "register status " + reg.status() };

  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/contrase/i).fill("secret123");
  await page.getByRole("button", { name: /entrar|iniciar/i }).click();
  await page.waitForSelector("text=Hola", { timeout: 10000 });

  await page.goto("http://localhost:5173/casa", { waitUntil: "domcontentloaded" });
  await page.getByRole("textbox", { name: "Título de la tarea" }).fill("Sacar la basura");
  await page.getByRole("button", { name: "Añadir", exact: true }).first().click();
  await page.getByText("Sacar la basura", { exact: true }).waitFor({ timeout: 8000 });

  const token = await page.evaluate(() => localStorage.getItem("loopy_token"));
  const cabecera = { Authorization: `Bearer ${token}` };
  const tareas = async () =>
    (await page.request.get(`${API}/api/tasks`, { headers: cabecera })).json();
  const buscar = async () => (await tareas()).find((t) => t.title === "Sacar la basura");

  // Nadie ha pedido avisos: el botón tiene que estar apagado.
  out.botonApagado = (await page.getByRole("button", { name: "Avisarme a una hora" }).count()) === 1;
  const antes = await buscar();
  out.noAvisaba = antes.notify === false && antes.due_at === null;

  // Encenderlo abre el editor de hora; el aviso no existe todavía.
  await page.getByRole("button", { name: "Avisarme a una hora" }).click();
  out.pideHora = (await page.getByLabel("Avisarme a las").count()) === 1;
  const sinGuardar = await buscar();
  out.noGuardaHastaPulsar = sinGuardar.notify === false;

  // Guardar 21:30 y comprobar lo que queda en la base de datos.
  await page.getByLabel("Avisarme a las").fill("21:30");
  await page.getByRole("button", { name: "Guardar", exact: true }).click();
  await page.getByRole("button", { name: /Quitar el aviso de las 21:30/ }).waitFor({ timeout: 8000 });

  const t = await buscar();
  out.activado = t.notify === true;
  out.horaGuardada = typeof t.due_at === "string" && t.due_at.slice(11, 16) === "21:30";
  // El scheduler trata `due_at` como reloj de pared (notify.py lo combina con el
  // día de la tarea y solo lee la hora), así que mandarlo con `Z` convertiría la
  // hora a la zona del usuario y el aviso saltaría a otra hora. Naive a propósito.
  out.sinZona = !/[zZ]|[+-]\d\d:?\d\d$/.test(t.due_at);
  out.botonEncendido = (await page.getByRole("button", { name: /Quitar el aviso de las 21:30/ }).count()) === 1;

  // Volver a apagarlo: el PATCH descarta los null, así que la hora sigue guardada
  // pero `notify` a false es lo que decide el scheduler (notify.py lo exige).
  await page.getByRole("button", { name: /Quitar el aviso de las 21:30/ }).click();
  await page.getByRole("button", { name: "Avisarme a una hora" }).waitFor({ timeout: 8000 });
  const apagado = await buscar();
  out.apagado = apagado.notify === false;
  out.botonVuelveAApagado = (await page.getByRole("button", { name: "Avisarme a una hora" }).count()) === 1;

  return out;
}
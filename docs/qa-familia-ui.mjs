import { randomUUID } from "node:crypto";

const APP = "http://localhost:5173";

/**
 * Flujo de la Fase 3: un adulto da de alta una cuenta de niño y el niño entra
 * con su nombre y su PIN.
 *
 * Se recorre entero y en el orden real: crear desde la cuenta adulta, ver el
 * PIN que se enseña una sola vez, salir, entrar por la puerta del niño, fallar
 * un intento a propósito y entrar bien.
 */
export default async function run(page, ui) {
  const email = `qa_familia_${Date.now()}_${randomUUID().slice(0, 6)}@gmail.com`;
  // Nombre único por pasada: el backend entra solo si exactamente una cuenta
  // coincide con nombre + PIN, así que repetir nombre y PIN deja al niño fuera.
  const nombre = `Nino${randomUUID().slice(0, 5)}`;
  const pin = "4821";
  const results = {};

  // ------------------------------------------------------------ adulto
  await page.goto(`${APP}/registro`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Contraseña (mín. 8 caracteres)").fill("secreto123");
  await page.getByRole("button", { name: "Crear cuenta" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  results.adulto = "registrado";

  // ------------------------------------------------------- alta de niño
  // Las etiquetas llevan el asterisco de obligatorio, así que se buscan por
  // prefijo y no por texto exacto.
  await page.goto(`${APP}/familia`, { waitUntil: "domcontentloaded" });
  await page.getByText("Todavía no hay ninguna cuenta de niño", { exact: false }).waitFor({ timeout: 10000 });

  await page.getByLabel(/^Nombre/).fill(nombre);
  await page.getByLabel(/^PIN/).fill(pin);
  await page.getByLabel(/^Fecha de nacimiento/).fill("2016-05-10");
  await page.getByLabel(/^Curso/).fill("4º de Primaria");
  await page.getByRole("button", { name: "Crear cuenta" }).click();

  // El PIN solo se enseña al crearlo: si no sale aquí, el adulto no puede
  // comunicárselo al niño y la cuenta queda inservible.
  const aviso = page.locator(".MuiAlert-message").filter({ hasText: "ya puede entrar con el PIN" });
  await aviso.waitFor({ timeout: 15000 });
  results.pinEnseñadoUnaVez = (await aviso.innerText()).replace(/\s+/g, " ").trim();
  results.avisaQueNoSeRecupera = (await aviso.innerText()).includes("no se puede recuperar");

  // Y la cuenta aparece en la lista, con su curso.
  await page.getByText(nombre, { exact: true }).waitFor({ timeout: 10000 });
  const tarjeta = page.getByText(/^Alta el /).locator("xpath=..");
  results.lista = (await tarjeta.innerText()).replace(/\s+/g, " ").trim();
  // El PIN no viaja en la lista: la cuenta solo guarda el hash.
  results.pinFueraDeLaLista = !(await tarjeta.innerText()).includes(pin);

  // Un nombre repetido rompería la entrada del niño, así que tiene que avisar
  // antes de dar de alta la cuenta. Con el PIN también puesto, porque si no
  // salta antes la validación del PIN y no se llega a comprobar el nombre.
  await page.getByLabel(/^Nombre/).fill(nombre.toUpperCase());
  await page.getByLabel(/^PIN/).fill("1234");
  await page.getByRole("button", { name: "Crear cuenta" }).click();
  await page.getByText("Ya hay una cuenta con el nombre", { exact: false }).waitFor({ timeout: 10000 });
  results.nombreRepetido = "avisado antes de crear";

  // ----------------------------------------------------------- salir
  await page.getByRole("button", { name: "Menú de cuenta" }).click();
  await page.getByRole("menuitem", { name: "Salir" }).click();
  await page.waitForURL((u) => u.pathname === "/login", { timeout: 10000 });
  results.salido = "vuelve al login";

  // ------------------------------------------------- puerta del niño
  // Es un Button de MUI con component={RouterLink}: se renderiza como <a>,
  // así que su rol es link, no button.
  await page.getByRole("link", { name: "Soy un niño, entrar con mi PIN" }).click();
  await page.waitForURL((u) => u.pathname === "/nino", { timeout: 10000 });
  results.puertaNino = (await page.locator("form").innerText()).replace(/\s+/g, " ").trim();

  // Un intento fallido a propósito: el error debe explicarse, no desaparecer.
  await page.getByLabel(/^¿Cómo te llamas\?/).fill(nombre);
  await page.getByLabel(/^Tu PIN/).fill("0000");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByText("Nombre o PIN incorrectos", { exact: false }).waitFor({ timeout: 15000 });
  results.pinIncorrecto = "avisa y deja reintentar";
  results.pinBorradoTrasFallar = (await page.getByLabel(/^Tu PIN/).inputValue()) === "";

  // Y ahora sí.
  await page.getByLabel(/^Tu PIN/).fill(pin);
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  await page.getByText("Qué toca hoy", { exact: true }).waitFor({ timeout: 15000 });
  results.entraElNino = "Mi día";
  // El niño ve su colegio, no el área de casa del adulto.
  results.navNino = (await page.locator("header").innerText()).replace(/\s+/g, " ").trim();

  return results;
}

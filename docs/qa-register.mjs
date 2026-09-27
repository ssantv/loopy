export default async function run(page, ui) {
  await page.goto("http://localhost:5173/registro");
  await page.waitForTimeout(600);
  const form = await ui.snapshot();

  const email = form.match(/@(e\d+) textbox "Email/)?.[1];
  const pass = form.match(/@(e\d+) textbox "Contraseña/)?.[1];
  const submit = form.match(/@(e\d+) button "CREAR CUENTA"/)?.[1];
  if (!email || !pass || !submit) return { error: "elementos no encontrados", form };

  const emailInput = ui.ref(email);
  const passInput = ui.ref(pass);
  await emailInput.fill(`qa_${Date.now()}@gmail.com`);
  await passInput.fill("secreto123");

  const afterFill = await ui.snapshot();
  const select = afterFill.match(/@(e\d+) combobox "Tipo de cuenta"/)?.[1];
  if (select) await ui.click(select);

  const menu = await ui.snapshot();
  const nino = menu.match(/@(e\d+) option "Niño"/)?.[1] ?? menu.match(/@(e\d+) option "Ni[ñn]o"/)?.[1];
  if (nino) await ui.click(nino);

  await ui.click(submit);
  await page.waitForTimeout(1200);

  const result = await ui.snapshot({ full: true });
  return {
    homeRendered: result.includes("Hola"),
    childGreeting: result.includes("Hola pequeño"),
    profileFound: nino ? "child" : null,
    body: result.slice(0, 300),
  };
}
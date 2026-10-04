export default async function run(page, ui) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console: ${m.text()}`);
  });
  const failed = [];
  page.on("requestfailed", (r) => failed.push(`${r.method()} ${r.url()} :: ${r.failure()?.errorText}`));

  // Por etiqueta y no por posición: el segundo textbox puede no haber pintado
  // todavía y `fill(undefined)` reventaba con "ref desconocida: undefined".
  const ref = async (pat) => {
    for (let intento = 0; intento < 20; intento++) {
      const id = (await ui.snapshot()).match(pat)?.[1];
      if (id) return id;
      await page.waitForTimeout(250);
    }
    return null;
  };

  const email = await ref(/@(e\d+) textbox "Email"/);
  await ui.fill(email, "prueba@prueba.es");
  await page.waitForTimeout(200);

  const pwd = await ref(/@(e\d+) textbox "Contrase\u00f1a"/);
  await ui.fill(pwd, "12345678");
  await page.waitForTimeout(200);

  const entrar = await ref(/@(e\d+) button "ENTRAR"/);
  await ui.click(entrar);
  await page.waitForTimeout(2000);

  const home = await ui.snapshot({ full: true });
  return { errors, failed, home };
}
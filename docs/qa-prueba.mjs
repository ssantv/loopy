export default async function run(page, ui) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console: ${m.text()}`);
  });
  const failed = [];
  page.on("requestfailed", (r) => failed.push(`${r.method()} ${r.url()} :: ${r.failure()?.errorText}`));

  const snap = await ui.snapshot();
  const email = snap.match(/@(e\d+) textbox/)?.[1];
  await ui.fill(email, "prueba@prueba.es");
  await page.waitForTimeout(200);

  const snap2 = await ui.snapshot();
  const pwd = [...snap2.matchAll(/@(e\d+) textbox/g)][1]?.[1];
  await ui.fill(pwd, "12345678");
  await page.waitForTimeout(200);

  const snap3 = await ui.snapshot();
  const entrar = snap3.match(/@(e\d+) button "ENTRAR"/)?.[1];
  await ui.click(entrar);
  await page.waitForTimeout(2000);

  const home = await ui.snapshot({ full: true });
  return { errors, failed, home };
}
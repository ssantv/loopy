export default async function run(page, ui) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });

  // 1. Cargar la página, esperar a que el SW tome control y recargue
  await page.waitForFunction(() => !!navigator.serviceWorker?.controller, null, { timeout: 15000 });
  await page.waitForTimeout(1500);

  // 2. Segunda recarga (como hace un usuario normal tras la 1a)
  await page.reload();
  await page.waitForTimeout(1500);

  const snap = await ui.snapshot();
  const email = [...snap.matchAll(/@(e\d+) textbox/g)][0]?.[1];
  if (email) await ui.fill(email, "prueba@prueba.es");
  await page.waitForTimeout(200);

  const snap2 = await ui.snapshot();
  const pwd = [...snap2.matchAll(/@(e\d+) textbox/g)][1]?.[1];
  if (pwd) await ui.fill(pwd, "12345678");
  await page.waitForTimeout(200);

  const snap3 = await ui.snapshot();
  const entrar = snap3.match(/@(e\d+) button "ENTRAR"/)?.[1] || snap3.match(/@(e\d+) button "Entrar"/)?.[1];
  if (entrar) await ui.click(entrar);
  await page.waitForTimeout(2500);

  const home = await ui.snapshot({ full: true });
  const swInfo = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.getRegistration();
    return { controlled: !!navigator.serviceWorker.controller, sw: reg?.active?.scriptURL ?? null };
  });
  return { errors, swInfo, home };
}
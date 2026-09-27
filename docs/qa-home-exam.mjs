export default async function run(page, ui) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console: ${m.text()}`);
  });

  const snap = await ui.snapshot();
  const email = snap.match(/@(e\d+) textbox/)?.[1];
  if (!email) return { error: "no email textbox", errors, snap };
  await ui.fill(email, "test_kid_1153@test.com");
  await page.waitForTimeout(200);

  const snap2 = await ui.snapshot();
  const pwd = [...snap2.matchAll(/@(e\d+) textbox/g)][1]?.[1];
  if (!pwd) return { error: "no password textbox", errors, snap2 };
  await ui.fill(pwd, "secret123");
  await page.waitForTimeout(200);

  const snap3 = await ui.snapshot();
  const entrar = snap3.match(/@(e\d+) button "ENTRAR"/)?.[1];
  if (!entrar) return { error: "no login button", errors, snap3 };
  await ui.click(entrar);
  await page.waitForTimeout(1500);

  const home = await ui.snapshot({ full: true });
  return {
    errors,
    hasResumen: home.includes("Resumen") || home.includes("resumen"),
    hasSociales: home.includes("Sociales"),
    hasNadaPendiente: home.includes("nada pendiente") || home.includes("No tienes nada"),
    home,
  };
}
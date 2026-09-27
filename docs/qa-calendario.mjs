export default async function run(page, ui) {
  const out = {};

  // --- login: formulario conocido (email 1er textbox, password 2º, botón Entrar) ---
  await page.waitForSelector("button", { timeout: 20000 });
  await page.waitForTimeout(500);
  let snap = await ui.snapshot();
  const boxes = [...snap.matchAll(/@(e\d+) textbox/g)].map((m) => m[1]);
  if (boxes.length < 2) return { error: "login fields not found", snap };
  await ui.fill(boxes[0], "prueba@prueba.es");
  await ui.fill(boxes[1], "12345678");
  await page.waitForTimeout(250);
  snap = await ui.snapshot();
  const submit = [...snap.matchAll(/@(e\d+) button "([^"]+)"/g)].find((m) => /entrar/i.test(m[2]))?.[1];
  if (!submit) return { error: "no submit button", snap };
  await ui.click(submit);
  await page.waitForSelector("text=Qué toca hoy", { timeout: 20000 });
  await page.waitForTimeout(800);

  // dejar limpio el día de hoy (desmarcar cualquier "Hecho")
  const tree = await ui.snapshot({ full: true });
  out.home = tree;
  out.hasPlan = tree.includes("Sociales") && tree.includes("Estudio");

  // --- toggle del plan item: marcar el estudio de hoy como hecho ---
  snap = await ui.snapshot();
  const row = [...snap.matchAll(/@(e\d+) button "([^"]*)"/g)].find((m) => /Sociales/.test(m[2]))?.[1];
  if (row) {
    const before = tree.includes("Hecho ✓");
    await ui.click(row);
    await page.waitForSelector("text=Hecho ✓", { timeout: 10000 }).catch(() => null);
    await page.waitForTimeout(200);
    const afterTree = await ui.snapshot({ full: true });
    out.toggledOn = before ? false : true;
    out.toggledDone = afterTree.includes("Hecho ✓");
    // desmarcar para dejar el día limpio (cada prueba que edita debe restaurar)
    const off = [...(await ui.snapshot()).matchAll(/@(e\d+) button "([^"]*)"/g)].find((m) => /Sociales/.test(m[2]))?.[1];
    if (off) await ui.click(off);
    await page.waitForTimeout(900);
  } else {
    out.noPlanRow = true;
  }

  // --- diálogo sesión adelantada ---
  snap = await ui.snapshot();
  const sesBtn = [...snap.matchAll(/@(e\d+) button "([^"]*)"/g)].find((m) => /sesión por mi cuenta/i.test(m[2]))?.[1];
  out.sesionSnap = snap;
  if (sesBtn) {
    await ui.click(sesBtn);
    await page.waitForTimeout(500);
    const dlg = await ui.snapshot({ full: true });
    out.sessionDialog = dlg.includes("Adelantar sesión");
    out.sessionSubjects = dlg.includes("Sociales");
    // cerrar
    const close = [...(await ui.snapshot()).matchAll(/@(e\d+) button "([^"]*)"/g)].find((m) => /Cerrar/i.test(m[2]))?.[1];
    if (close) await ui.click(close);
    await page.waitForTimeout(400);
  } else {
    out.noSessionButton = true;
  }

  // --- navegar al calendario ---
  snap = await ui.snapshot();
  out.calSnap = snap;
  const calBtnAtHome = [...snap.matchAll(/@(e\d+) link "([^"]*)"/g)].find((m) => /calendario/i.test(m[2]))?.[1];
  if (calBtnAtHome) {
    await ui.click(calBtnAtHome);
    await page.waitForSelector("text=Semana", { timeout: 10000 });
    await page.waitForTimeout(1200);
    snap = await ui.snapshot({ full: true });
    out.calendario = snap;
    out.calHasSemana = snap.includes("Semana");
    out.calHasMes = snap.includes("Mes");
    out.calHasPlan = snap.includes("Sociales");
    // toggle a mes
    const mes = [...(await ui.snapshot()).matchAll(/@(e\d+) button "([^"]*)"/g)].find((m) => /^mes$/i.test(m[2]))?.[1];
    if (mes) {
      await ui.click(mes);
      await page.waitForTimeout(1200);
      snap = await ui.snapshot({ full: true });
      out.mesView = snap.includes("sep") || snap.includes("sept");
      out.mesHasPlan = snap.includes("Sociales");
    } else {
      out.noMesButton = true;
    }

    // volver a semana y marcar/desmarcar el plan del día de hoy
    const semana = [...(await ui.snapshot()).matchAll(/@(e\d+) button "([^"]*)"/g)].find((m) => /^semana$/i.test(m[2]))?.[1];
    if (semana) await ui.click(semana);
    await page.waitForTimeout(1200);
    snap = await ui.snapshot();
    const chip = [...snap.matchAll(/@(e\d+) button "([^"]*)"/g)].find((m) => /Sociales · Estudio/.test(m[2]))?.[1];
    if (chip) {
      const before = await page.locator(".MuiChip-root .Mui-checked").count();
      await ui.click(chip);
      await page.waitForTimeout(1200);
      const after = await page.locator(".MuiChip-root .Mui-checked").count();
      out.calToggled = { before, after };
      out.afterCalClick = await ui.snapshot({ full: true });
      out.calErrors = await page.locator("[role=alert]").allInnerTexts();
      // restaurar: desmarcar si seguía sin ser done
      if (after > before) {
        const chip2 = [...(await ui.snapshot()).matchAll(/@(e\d+) button "([^"]*)"/g)].find((m) => /Sociales · Estudio/.test(m[2]))?.[1];
        if (chip2) await ui.click(chip2);
        await page.waitForTimeout(1200);
        out.calRestored = (await page.locator(".MuiChip-root .Mui-checked").count()) === before;
      } else {
        out.calRestored = true;
      }
    } else {
      out.noChip = true;
    }
  } else {
    out.noCalButton = true;
  }

  return out;
}
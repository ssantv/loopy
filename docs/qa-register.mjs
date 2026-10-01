/**
 * El registro es solo de adultos: se comprueba que el perfil de niño ya no se
 * ofrece ahí, y que un adulto se registra y entra con su email y contraseña.
 */
export default async function run(page, ui) {
  await page.goto("http://localhost:5173/registro");
  await page.waitForTimeout(600);
  // El árbol completo es para leer, pero los refs (@e1) solo salen en el plano.
  const form = await ui.snapshot();
  const arbol = await ui.snapshot({ full: true });

  const email = form.match(/@(e\d+) textbox "Email/)?.[1];
  const pass = form.match(/@(e\d+) textbox "Contraseña/)?.[1];
  const submit = form.match(/@(e\d+) button "CREAR CUENTA"/)?.[1];
  if (!email || !pass || !submit) return { error: "elementos no encontrados", form };

  // Lo que ya no debe existir en esta pantalla.
  const sinTipoDeCuenta = !arbol.includes("Tipo de cuenta");
  const sinCumple = !/Fecha de nacimiento/i.test(arbol);
  const avisaDeNinos = /los niños no se registran|creas su cuenta con un PIN/i.test(arbol);

  await ui.fill(email, `qa_${Date.now()}@gmail.com`);
  await ui.fill(pass, "secreto123");
  await ui.click(submit);
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });

  const result = await ui.snapshot({ full: true });
  return {
    sinTipoDeCuenta,
    sinCumple,
    avisaDeNinos,
    // El adulto entra en su "Mi día" (saluda con "Hola"); el niño, en "Qué toca hoy".
    homeAdulto: result.includes('heading "Hola"'),
    navAdulto: /link "Casa"/.test(result) && /link "Calendario"/.test(result),
    body: result.slice(0, 300),
  };
}

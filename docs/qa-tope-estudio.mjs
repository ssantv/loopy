// QA del tope de estudio en Perfil: lo que se escribe ahí es lo mismo que usa
// el reparto del plan y el aviso de "no cabe".
export default async function run(page, ui) {
  const tag = Date.now();
  const email = `qa_tope_${tag}@gmail.com`;
  const nombre = `Nico${tag}`;
  const hoy = new Date();
  const hoyISO = hoy.toISOString().slice(0, 10);

  await page.evaluate(
    async ({ email, nombre, hoyISO }) => {
      const base = "http://localhost:5173";
      const j = async (p, body, token) => {
        const res = await fetch(base + p, {
          method: body ? "POST" : "GET",
          headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: body ? JSON.stringify(body) : undefined,
        });
        return { status: res.status, body: await res.json().catch(() => null) };
      };
      const adulto = await j("/api/auth/register", { email, password: "secreto123", profile_type: "adult" });
      await j("/api/auth/children", { display_name: nombre, pin: "4821", birth_date: "2015-05-10" }, adulto?.body?.token);
      await j("/api/auth/child-login", { display_name: nombre, pin: "4821" });
    },
    { email, nombre, hoyISO },
  );

  await page.goto("http://localhost:5173/nino");
  await page.getByLabel(/^¿Cómo te llamas\?/).fill(nombre);
  await page.getByLabel(/^Tu PIN/).fill("4821");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  await page.waitForTimeout(2000);

  await page.goto("http://localhost:5173/perfil");
  await page.waitForTimeout(1500);
  const antes = await ui.snapshot({ full: true });
  const hayCampo = /Minutos al d[ií]a/.test(antes);
  const valorPorDefecto = await page.getByLabel("Minutos al día").inputValue();

  await page.getByLabel("Minutos al día").fill("45");
  await page.getByLabel("Minutos al día").press("Enter");
  await page.waitForTimeout(1500);

  const guardado = await page.evaluate(async () => {
    const r = await fetch("http://localhost:5173/api/auth/me", {
      headers: { Authorization: `Bearer ${localStorage.getItem("loopy_token")}` },
    });
    const carga = await fetch("http://localhost:5173/api/day-load", {
      headers: { Authorization: `Bearer ${localStorage.getItem("loopy_token")}` },
    });
    return { me: await r.json(), carga: await carga.json() };
  });

  // 0 = sin tope: el reparto deja de limitar.
  await page.getByLabel("Minutos al día").fill("0");
  await page.getByLabel("Minutos al día").press("Enter");
  await page.waitForTimeout(1500);
  const sinTope = await page.evaluate(async () => {
    const carga = await fetch("http://localhost:5173/api/day-load", {
      headers: { Authorization: `Bearer ${localStorage.getItem("loopy_token")}` },
    });
    return carga.json();
  });

  // Vaciar el campo y salir sin tocar nada no puede desactivar el tope: 0 aquí
  // significa "sin límite", así que un blur sin querer se llevaría la protección
  // del niño sin que nadie la pidiera. El input debe volver a su último valor.
  await page.getByLabel("Minutos al día").fill("");
  await page.getByLabel("Minutos al día").blur();
  await page.waitForTimeout(1200);
  const trasVaciar = await page.evaluate(async () => {
    const me = await fetch("http://localhost:5173/api/auth/me", {
      headers: { Authorization: `Bearer ${localStorage.getItem("loopy_token")}` },
    });
    return me.json();
  });
  const campoVuelto = await page.getByLabel("Minutos al día").inputValue();

  return {
    hayCampo,
    valorPorDefecto,
    // El valor guardado es el que devuelven el perfil y la carga del día: si
    // Perfil escribiera en otro sitio, el reparto seguiría con 60.
    topeEnPerfil: guardado.me.study_max_minutes === 45,
    topeEnCarga: guardado.carga.daily_max_minutes === 45,
    ceroEsSinTope: sinTope.daily_max_minutes === 0 && sinTope.over_cap_minutes === 0,
    vaciarNoGuarda: trasVaciar.study_max_minutes === 0 && campoVuelto === "0",
  };
}
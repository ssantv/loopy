// QA de la línea del día completa (citas + comidas + huecos) y de la pantalla de
// extraescolares del niño.
//
// Dos cosas que se comprueban aquí y que son fáciles de romper sin que se note:
//
// 1. Las comidas se **muestran** pero no se **cobran**. Si `_comidas_del_dia`
//    empezara a sumar en `day-load`, el reparto de estudio de quien ya tiene plan
//   _mounted cambiaría de un día para otro sin que nadie lo pidiera.
// 2. Los huecos son el complemento de los bloques. Si se calcularan restando sin
//    más, dos citas solapadas dejarían un hueco fantasma en medio.
export default async function run(page, ui) {
  const tag = Date.now();
  const email = `qa_linea_${tag}@gmail.com`;
  const nombre = `Nico${tag}`;
  const hoyISO = new Date().toISOString().slice(0, 10);
  // Lunes de una semana fija, para que el día de la semana no dependa de hoy.
  const LUNES = "2026-09-21";

  const sembrado = await page.evaluate(
    async ({ email, nombre, LUNES }) => {
      const base = "http://localhost:5173";
      // El método va aparte y explícito: el menú se siembra con PATCH y PUT, y
      // colarlos por POST devolvía 405 en silencio y las comidas no se crearían.
      const j = async (p, body, token, method) => {
        const res = await fetch(base + p, {
          method: method ?? (body ? "POST" : "GET"),
          headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: body ? JSON.stringify(body) : undefined,
        });
        return { status: res.status, body: await res.json().catch(() => null) };
      };
      const madre = await j("/api/auth/register", { email, password: "secreto123", profile_type: "adult" });
      const token = madre?.body?.token;
      const hijo = await j(
        "/api/auth/children",
        { display_name: nombre, pin: "4821", birth_date: "2015-05-10", timezone: "UTC" },
        token,
      );

      // Comida activada con plato planificado, y merienda sin nada planificado.
      const slotComida = await j("/api/menu/slots/comida", { enabled: true, default_time: "14:00:00" }, token, "PATCH");
      const slotMerienda = await j("/api/menu/slots/merienda", { enabled: true, default_time: "17:45:00" }, token, "PATCH");
      const plan = await j(`/api/menu/plan/${LUNES}/comida`, { free_text: "Lubina con patatas" }, token, "PUT");

      // Dos citas solapadas: el solape no debe dejar un hueco de un minuto.
      await j(
        "/api/appointments",
        { title: "Dentista", date: LUNES, start_time: "10:00", end_time: "12:00" },
        token,
      );
      await j(
        "/api/appointments",
        { title: "Recogida", date: LUNES, start_time: "11:00", end_time: "13:00" },
        token,
      );

      const tl = await j(`/api/day-timeline?date=${LUNES}`, null, token);
      const sembradoEstados = {
        slotComida: slotComida.status,
        slotMerienda: slotMerienda.status,
        plan: plan.status,
      };
      const carga = await j(`/api/day-load?date=${LUNES}`, null, token);
      const hijoId = hijo?.body?.id;
      const login = await j("/api/auth/child-login", { display_name: nombre, pin: "4821" });
      return {
        token,
        hijoId,
        niñotoken: login?.body?.token,
        timeline: tl,
        carga: carga?.body,
        sembradoEstados,
      };
    },
    { email, nombre, LUNES },
  );

  if (sembrado.timeline?.status !== 200) {
    return { error: `endpoint day-timeline no disponible (${sembrado.timeline?.status})`, sembrado };
  }

  await page.goto("http://localhost:5173/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/contrase/i).fill("secreto123");
  await page.getByRole("button", { name: /Entrar/i }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  await page.waitForTimeout(2000);

  // El timeline se pide sin fecha (es "hoy"), así que se mira la API para el lunes y
  // la pantalla solo para comprobar que el dibujo no rompe. Son dos cosas distintas:
  // la API responde a una fecha concreta, la pantalla enseña la de hoy.
  const tl = sembrado.timeline.body;
  const carga = sembrado.carga;

  const comidas = tl.blocks.filter((b) => b.kind === "comida");
  const muestraComida = comidas.some((b) => b.title === "Lubina con patatas" && b.slot === "comida");
  const muestraFranjaSinPlato = comidas.some((b) => b.slot === "merienda" && b.title === "Merienda");
  const duracionComida = comidas.find((b) => b.slot === "comida")?.minutes === 60;

  // 1) Las comidas no se cobran, y el solape tampoco: 10:00-13:00 son 180 minutos,
  // aunque las dos citas duren 2 h, y 0 minutos de comer.
  const noSeCobran = carga.appointment_minutes === 180 && carga.blocked_minutes === 180;
  const comidaNoEntraEnLaCarga = tl.blocked_minutes === carga.blocked_minutes;

  // 2) Huecos: complemento de la unión, con las comidas partiendo el día.
  const huecos = tl.huecos.map((h) => `${h.start.slice(0, 5)}-${h.end.slice(0, 5)}`);
  const esperadoHuecos = ["07:00-10:00", "13:00-14:00", "15:00-17:45", "18:05-23:00"];
  const huecosOK = JSON.stringify(huecos) === JSON.stringify(esperadoHuecos);
  const sinHuecoFantasma = !huecos.some((h) => h === "12:00-12:00" || h === "12:00-11:00");
  const sumaMinutos = tl.huecos.reduce((a, h) => a + h.minutes, 0) === tl.free_minutes;

  // Lo que dice la carga y lo que se puede colocar tienen que salir de la misma
  // ventana de 16 h. Es lo único que se necesita para que no haya minutos
  // inventados: lo ocupado (bloqueado), lo libre (huecos) y lo de comer, que se
  // muestra pero no se cobra contra el estudio. Esta es la comprobación que
  // fallaba cuando el solape se sumaba dos veces.
  const minutosComida = tl.blocks.filter((b) => b.kind === "comida").reduce((a, b) => a + b.minutes, 0);
  const ventanaCuadra =
    carga.blocked_minutes + tl.free_minutes + minutosComida === 16 * 60
    && tl.blocked_minutes === carga.blocked_minutes;

  // 3) La pantalla pinta la línea sin romperse y con los huecos visibles.
  await page.waitForTimeout(1500);
  const texto = await page.evaluate(() => document.body.innerText);
  const lineaPintada = /Tu l\u00ednea del d\u00eda/.test(texto) || texto.includes("Tu linea del dia");

  // 4) El niño gestiona sus extraescolares y marca quién tiene que llevarle.
  // Hay que salir de la sesión del adulto antes: con el token vivo, `/nino`
  // redirige a "/" y el input del login se desmonta mientras se rellena.
  await page.getByRole("button", { name: "Menú de cuenta" }).click();
  await page.getByRole("menuitem", { name: "Salir" }).click();
  await page.waitForURL((u) => u.pathname === "/login", { timeout: 10000 });
  // Se entra con carga completa y no con el link del login: al navegar dentro de la
  // SPA quedaban los dos formularios a la vez y el botón no enviaba nada.
  await page.goto("http://localhost:5173/nino");
  await page.waitForTimeout(1000);
  await page.getByLabel(/^\u00bfC\u00f3mo te llamas\?/).fill(nombre);
  await page.getByLabel(/^Tu PIN/).fill("4821");
  await page.getByRole("button", { name: "Entrar" }).click();
  try {
    await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  } catch {
    const visible = await page.evaluate(() => document.body.innerText);
    return { error: "el niño no entró", url: page.url(), visible: visible.slice(0, 200) };
  }
  await page.goto("http://localhost:5173/colegio");
  await page.waitForTimeout(2500);

  const t0 = await page.evaluate(() => document.body.innerText);
  const seccionExtra = /Extraescolares/.test(t0);
  const vacia = /No tienes ninguna extraescolar/.test(t0);

  // Todo se acota a la sección: en Colegio hay otro "Añadir" (asignaturas) y otro
  // "Día" (exámenes), y sin acotar el selectorMatching es ambiguo.
  const extras = page.locator("section").filter({ hasText: "Extraescolares" });
  await extras.getByLabel("Actividad").fill("Natación");
  await extras.getByLabel("Día").click();
  await page.getByRole("option", { name: "Lunes" }).click();
  await extras.getByRole("button", { name: "Añadir" }).click();
  await page.waitForTimeout(2000);
  const t1 = await page.evaluate(() => document.body.innerText);
  const creada = /Nataci\u00f3n/.test(t1) && /Lunes/.test(t1);

  // El checkbox es el punto de todo esto: sin marcarlo, el adulto no pierde la hora.
  await extras.getByRole("checkbox", { name: "Me tienen que llevar a Natación" }).check();
  await page.waitForTimeout(2000);
  const marcado = await extras.getByRole("checkbox", { name: "Me tienen que llevar a Natación" }).isChecked();

  const guardado = await page.evaluate(async ({ hijoId, LUNES }) => {
    const token = localStorage.getItem("loopy_token");
    const r = await fetch("http://localhost:5173/api/extracurriculars", {
      headers: { Authorization: `Bearer ${token}` },
    });
    const lista = await r.json();
    const x = lista.find((e) => e.name === "Nataci\u00f3n");
    return { hay: !!x, affects_parent: x?.affects_parent ?? null, day_of_week: x?.day_of_week ?? null, hijoId, LUNES };
  }, { hijoId: sembrado.hijoId, LUNES });

  // Y el adulto lo ve como "llevar a", que es lo que le quita la hora.
  const enP_adulto = await page.evaluate(async ({ email, LUNES }) => {
    const r = await fetch("http://localhost:5173/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password: "secreto123" }),
    });
    const sesion = await r.json();
    const tl = await (
      await fetch(`http://localhost:5173/api/day-timeline?date=${LUNES}`, {
        headers: { Authorization: `Bearer ${sesion.token}` },
      })
    ).json();
    const comp = tl.blocks.filter((b) => b.kind === "extraescolar_compartida");
    return { count: comp.length, affected: comp[0]?.affected ?? [], minutes: comp[0]?.minutes ?? 0 };
  }, { email, LUNES });

  const elAdultoLoLleva =
    enP_adulto.count === 1 && enP_adulto.affected.includes(nombre) && enP_adulto.minutes === 60;

  return {
    muestraComida,
    muestraFranjaSinPlato,
    duracionComida,
    noSeCobran,
    comidaNoEntraEnLaCarga,
    huecosOK,
    sinHuecoFantasma,
    sumaMinutos,
    lineaPintada,
    seccionExtra,
    vacia,
    creada,
    marcado,
    guardadoOk: guardado.affects_parent === true && guardado.day_of_week === 0,
    elAdultoLoLleva,
    huecos,
    ventanaCuadra,
    cargaMin: { citas: carga.appointment_minutes, total: carga.blocked_minutes },
  };
}
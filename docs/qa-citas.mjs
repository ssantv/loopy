// QA de la línea de tiempo de "Mi día": las citas se pintan, el adulto las crea,
// las edita sin perder la recurrencia y las borra, y los minutos que dice la línea
// son los mismos que dice la carga del día.
//
// Por qué no basta con leer la pantalla: el fallo que importa aquí es invisible en
// un `tsc` en verde. Editar una cita mensual sin abrirla entera es exactamente el
// camino por el que una cita semanal se convierte en puntual sin que nadie se entere,
// así que el guion edita una semanal y comprueba que sigue siendo semanal.
export default async function run(page, ui) {
  const tag = Date.now();
  const email = `qa_citas_${tag}@gmail.com`;
  const nombre = `Nico${tag}`;
  const hoyISO = new Date().toISOString().slice(0, 10);

  // Siembra por API: una cita puntual que le afecta al niño y otra semanal solo del
  // adulto. Se siembran por API y no por pantalla a propósito: lo que se prueba aquí
  // es la línea de tiempo y el CRUD, no el formulario de alta.
  const sembrado = await page.evaluate(
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
      const token = adulto?.body?.token;
      const hijo = await j(
        "/api/auth/children",
        { display_name: nombre, pin: "4821", birth_date: "2015-05-10", timezone: "UTC" },
        token,
      );

      const cita = await j(
        "/api/appointments",
        {
          title: "Dentista",
          place: "Clínica Norte",
          date: hoyISO,
          start_time: "17:00",
          end_time: "18:00",
          affected_user_ids: [hijo?.body?.id],
        },
        token,
      );
      const semanal = await j(
        "/api/appointments",
        {
          title: "Piscina",
          date: hoyISO,
          start_time: "19:00",
          end_time: "20:00",
          repeats_weekly: true,
        },
        token,
      );

      const tl = await j(`/api/day-timeline?date=${hoyISO}`, null, token);
      const carga = await j("/api/day-load", null, token);
      return {
        token,
        hijoId: hijo?.body?.id,
        citaId: cita?.body?.id,
        semanalId: semanal?.body?.id,
        timeline: tl,
        carga: carga?.body,
      };
    },
    { email, nombre, hoyISO },
  );

  // Si el endpoint no existiera, el catch de la pantalla deja la sección sin pintar
  // y el guion pasaría sin comprobar nada. Se pregunta antes de mirar nada.
  if (sembrado.timeline?.status !== 200) {
    return { error: `endpoint day-timeline no disponible (${sembrado.timeline?.status})`, sembrado };
  }
  if (!sembrado.citaId || !sembrado.semanalId) {
    return { error: "no se pudieron sembrar las citas", sembrado };
  }

  await page.goto("http://localhost:5173/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/contrase/i).fill("secreto123");
  await page.getByRole("button", { name: /Entrar/i }).click();
  await page.waitForURL((u) => u.pathname === "/", { timeout: 15000 });
  await page.waitForTimeout(2500);

  const texto = () => page.evaluate(() => document.body.innerText);

  // 1) Las dos citas occupy el día, con su hora y el nombre de a quién afectan.
  const t1 = await texto();
  const muestraSeccion = /Tu línea del día/.test(t1);
  const muestraPuntual = t1.includes("17:00\u201318:00") && t1.includes("Dentista");
  // El niño se nombra solo si la cita le afecta: es lo que distingue un bloque de
  // "para mí" de uno que obliga a llevar a alguien.
  const nombraAlNino = t1.includes(nombre);
  const muestraSemanal = t1.includes("19:00\u201320:00") && t1.includes("cada semana");
  const muestraLugar = t1.includes("Clínica Norte");

  // 2) La carga del día cuenta los minutos de citas, y son los mismos que el
  // timeline: si divergen, la pantalla está diciendo dos cosas distintas.
  const bloqueadoTimeline = sembrado.timeline.body.blocks.reduce((a, b) => a + b.minutes, 0);
  const cuentaCoincide =
    sembrado.carga?.appointment_minutes === bloqueadoTimeline &&
    sembrado.carga?.appointments_count === 2;

  // 3) Crear una cita desde la pantalla y verla aparecer sin recargar a mano.
  await page.getByRole("button", { name: /\+ Cita/ }).click();
  await page.waitForTimeout(500);
  await page.getByLabel("Qué es").fill("Buyatodo");
  await page.getByLabel("Dónde").fill("Supermercado");
  await page.getByLabel("Desde").fill("16:00");
  await page.getByLabel("Hasta").fill("16:30");
  // El adulto es el afectado implícito: no se marca a nadie y la cita es suya.
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForTimeout(2000);
  const t2 = await texto();
  const creadaPorPantalla = t2.includes("Buyatodo") && t2.includes("16:00\u201316:30");

  // 4) Editar la semanal sin tocar la recurrencia: si el PUT manda la cita entera
  // como puntual, "cada semana" desaparece. Esto es lo que se comprueba.
  await page.getByRole("button", { name: "Editar Piscina" }).click();
  await page.waitForTimeout(500);
  await page.getByLabel("Dónde").fill("Polideportivo");
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForTimeout(2000);
  const t3 = await texto();
  const editada = t3.includes("Polideportivo");
  const conservaSemanal = t3.includes("cada semana");

  // 5) Borrar la cita creada y comprobar que desaparece de la línea de tiempo.
  await page.getByRole("button", { name: "Borrar Buyatodo" }).click();
  await page.waitForTimeout(2000);
  const t4 = await texto();
  const borrada = !t4.includes("Buyatodo");

  return {
    muestraSeccion,
    muestraPuntual,
    nombraAlNino,
    muestraSemanal,
    muestraLugar,
    cuentaCoincide,
    creadaPorPantalla,
    editada,
    conservaSemanal,
    borrada,
    minutos: { timeline: bloqueadoTimeline, carga: sembrado.carga?.appointment_minutes },
  };
}
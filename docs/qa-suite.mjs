// Suite completa de QA de navegador: `npm run qa` (dev) / `npm run qa:build`.
//
// Por qué existe y por qué no basta con lanzar los guiones sueltos: cada uno crea
// cuentas en la BD de desarrollo, veinte y pico ejecuciones manuales no las
// limpian y se acaba viendo verde sin saber qué se probó. Cada guion pasa por
// `qa_run.py`, que borra en cascada lo que creó, y este runner resume el veredicto
// de todos en una tabla.
//
// Reglas que importan más que los guiones:
//
// - **Un guion que devuelve `{error}` es un fallo**, aunque salga con código 0.
//   Los dos guiones de push no pueden correr contra `npm run dev` porque el
//   service worker solo se registra en producción; en vez de fingir que pasaron,
//   dicen por qué y aquí cuentan como rojo.
// - **Los guiones marcados `necesitaBuild` van contra el build**, no contra el dev
//   server. Se ejecutan solo con `--build` y con `npm run qa` se informa de que
//   se han quedado sin probar.
//
// Uso:
//     npm run qa                     # lo que aguanta el dev server
//     npm run qa:build               # solo lo que necesita el build servido
//     node docs/qa-suite.mjs --solo=home   # un subconjunto, para iterar
//     node docs/qa-suite.mjs --verbose     # con los volcados de pantalla
//
// `npm run qa:build` ejecuta **solo** los guiones marcados `necesitaBuild`:
// apuntarlos al build no los hace más válidos, los hace inalcanzables, porque la
// mayoría tienen la URL del dev server escrita dentro.
//
// Necesita la API en :8000 y el servidor indicado. Para el build:
//     frontend> npm run build && npm run preview
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const RAIZ = path.resolve(import.meta.dirname, "..");
const DRIVER = "docs/qa-driver.mjs";
const DEV = "http://localhost:5173";
const BUILD = "http://localhost:4173";

const argv = process.argv.slice(2);
const solo = argv.find((a) => a.startsWith("--solo="))?.split("=")[1] ?? null;
const soloBuild = argv.includes("--build");
const verbose = argv.includes("--verbose");

// Campos que son volcados de pantalla: pesan mucho y esconden los fallos reales.
const RUIDO =
  /^(body|home|snap|snap2|snap3|arbol|form|tree|afterCalClick|notas?|asignaciones|sesion|sesionSnap|cuerpo|calendario|calSnap|now|ahora|volcado)$/i;

function guiones() {
  return readdirSync(path.join(RAIZ, "docs"))
    .filter((f) => /^qa-.*\.mjs$/.test(f))
    .filter((f) => f !== "qa-driver.mjs" && f !== "qa-suite.mjs")
    .filter((f) => !solo || f.includes(solo))
    .sort();
}

// `necesitaBuild` lo declara el propio guion: quien lo escribe sabe si necesita
// el service worker, quien corre la suite no tiene que saberlo.
async function necesitaBuild(f) {
  // `pathToFileURL` es obligatorio: en Windows, `import("C:\\...")` se interpreta
  // como un esquema de URL desconocido y revienta con ERR_UNSUPPORTED_ESM_URL_SCHEME.
  const mod = await import(pathToFileURL(path.join(RAIZ, "docs", f)).href);
  return mod.necesitaBuild === true;
}

function correr(baseUrl, guion) {
  const r = spawnSync(
    "python",
    ["docs/qa_run.py", "--", "node", DRIVER, baseUrl, "--script", `docs/${guion}`],
    { cwd: RAIZ, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  return { salida: r.stdout ?? "", codigo: r.status ?? 1 };
}

function veredicto(salida) {
  const ini = salida.indexOf("{");
  const fin = salida.lastIndexOf("}");
  if (ini === -1 || fin <= ini) return { datos: null, motivo: "el guion no devolvió JSON" };
  try {
    return { datos: JSON.parse(salida.slice(ini, fin + 1)), motivo: null };
  } catch {
    return { datos: null, motivo: "el guion devolvió algo que no es JSON" };
  }
}

const lista = guiones();
let rojos = 0;
let probados = 0;
const sinProbar = [];

for (const guion of lista) {
  const conBuild = await necesitaBuild(guion);
  // Cada pasada cubre un mundo: la del dev server deja fuera lo que necesita el
  // build, y al revés. Ejecutar un guion de UI contra el build solo añadiría
  // ruido: sus `goto` apuntan a :5173 y acabarían probando el dev server igual.
  if (conBuild !== soloBuild) {
    sinProbar.push(guion);
    continue;
  }

  const baseUrl = conBuild ? BUILD : DEV;
  const { salida, codigo } = correr(baseUrl, guion);
  const { datos, motivo } = veredicto(salida);
  probados += 1;

  if (!datos) {
    rojos += 1;
    console.log(`\n### ${guion}  FALLO: ${motivo} (código ${codigo})`);
    console.log(salida.slice(-1200));
    continue;
  }

  // `{error}` es un fallo con voz propia: casi siempre es "no se puede probar aquí".
  if (datos.error) {
    rojos += 1;
    console.log(`\n### ${guion}  FALLO: ${datos.error}`);
    continue;
  }

  const plano = {};
  for (const [k, v] of Object.entries(datos)) {
    if (RUIDO.test(k) && !verbose) continue;
    plano[k] = typeof v === "object" && v !== null ? JSON.stringify(v).slice(0, 90) : v;
  }
  const falsos = Object.entries(plano).filter(([, v]) => v === false);
  if (falsos.length) rojos += 1;
  console.log(`\n### ${guion}${conBuild ? "  (build)" : ""}  ${falsos.length ? "FALLO" : "ok"}`);
  console.log(`  ${JSON.stringify(plano)}`);
}

const donde = soloBuild ? "el build" : "el dev server";
console.log(`\n${probados - rojos}/${probados} guiones en verde contra ${donde}`);
if (sinProbar.length) {
  const otro = soloBuild ? "npm run qa" : "npm run qa:build";
  const motivo = soloBuild ? "no necesitan el build" : "necesitan el build servido";
  console.log(`Fuera de esta pasada (${motivo}, pásate con \`${otro}\`):`);
  console.log(`  ${sinProbar.join("  ")}`);
}
process.exitCode = rojos ? 1 : 0;

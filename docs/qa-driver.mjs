// Driver de QA del navegador: `node docs/qa-driver.mjs <baseUrl> --script docs/qa-x.mjs`
//
// Monta un Chromium de verdad y expone tres cosas al guion: `page` (Playwright
// normal), un `snapshot()` del árbol accesible y `fill`/`click` que aceptan los
// refs `@eN` de ese snapshot. Los guiones comparan texto, así que no necesitan
// selectores ni saber nada del DOM: si reescriben un texto de la interfaz, el
// guion falla y no la app.
//
// Uso normal: quien lo llama es `qa_run.py`, que además limpia las cuentas que
// el guion cree. Para un solo guion:
//     python docs/qa_run.py -- node docs/qa-driver.mjs http://localhost:5173 \
//         --script docs/qa-home.mjs
import { pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

const [baseUrl, ...rest] = process.argv.slice(2);
const i = rest.indexOf("--script");
if (!baseUrl || i === -1) {
  console.error("uso: node docs/qa-driver.mjs <baseUrl> --script docs/qa-x.mjs");
  process.exit(2);
}
const guion = (await import(pathToFileURL(rest[i + 1]).href)).default;

let navegador;
try {
  navegador = await chromium.launch();
} catch (e) {
  // El fallo real de Playwright ("Executable doesn't exist at %LOCALAPPDATA%...")
  // no dice qué hacer. Esto sí.
  console.log(
    JSON.stringify(
      {
        error:
          "no se pudo abrir Chromium. Se instala con `npx playwright-core install chromium` " +
          `en la raíz del repo. Detalle: ${e?.message?.split("\n")[0] ?? String(e)}`,
      },
      null,
      2,
    ),
  );
  process.exit(1);
}
const contexto = await navegador.newContext({ viewport: { width: 390, height: 844 } });
const page = await contexto.newPage();

let cdp = null;
const refs = new Map();

// MUI aplica `text-transform: uppercase` a botones y a la navegación, así que el
// nombre accesible sale "CASA" mientras el código escribe "Casa". Los guiones
// comprueban las dos cosas según el caso, así que se emiten ambas formas con el
// mismo ref: si no, media suite falla por mayúsculas y parece un bug de la app.
async function refrescar() {
  cdp ??= await contexto.newCDPSession(page);
  await cdp.send("Accessibility.enable");
  const { nodes } = await cdp.send("Accessibility.getFullAXTree");
  refs.clear();

  const textoEnMemo = new Map();
  const textoDe = async (backendNodeId) => {
    if (textoEnMemo.has(backendNodeId)) return textoEnMemo.get(backendNodeId);
    let texto = null;
    try {
      const { object } = await cdp.send("DOM.resolveNode", { backendNodeId });
      const { result } = await cdp.send("Runtime.callFunctionOn", {
        objectId: object.objectId,
        functionDeclaration: "function () { return this.textContent ?? null; }",
        returnByValue: true,
      });
      texto = (result.value ?? "").trim();
    } catch {
      texto = null;
    }
    textoEnMemo.set(backendNodeId, texto);
    return texto;
  };

  const lineas = [];
  for (const n of nodes) {
    if (n.ignored || !n.role?.value) continue;
    const nombre = (n.name?.value ?? "").trim();
    if (!nombre && !["textbox", "button"].includes(n.role.value)) continue;
    // Los inputs no tienen textContent: ahí el nombre accesible es lo único.
    const codigo = await textoDe(n.backendDOMNodeId);
    if (!nombre && !codigo) continue;

    const id = `e${refs.size + 1}`;
    refs.set(id, n.backendDOMNodeId);
    lineas.push(`@${id} ${n.role.value} "${nombre}"`);
    if (codigo && codigo !== nombre) lineas.push(`@${id} ${n.role.value} "${codigo}"`);
  }
  return lineas;
}

// Playwright no expone los backendNodeId del árbol accesible, así que la vuelta al
// DOM se hace por CDP: se marca el elemento con un id y se busca por `#id`.
async function aSelector(id) {
  const backendNodeId = refs.get(id);
  if (!backendNodeId) throw new Error(`ref desconocida: ${id}`);
  const { object } = await cdp.send("DOM.resolveNode", { backendNodeId });
  const { result } = await cdp.send("Runtime.callFunctionOn", {
    objectId: object.objectId,
    functionDeclaration: `function () {
      if (!(this instanceof Element)) return null;
      if (!this.id) this.id = "qa-ref-" + Math.random().toString(36).slice(2);
      return "#" + CSS.escape(this.id);
    }`,
    returnByValue: true,
  });
  const sel = result.value;
  if (!sel) throw new Error(`no se pudo resolver ${id}`);
  return sel;
}

const ui = {
  snapshot: async ({ full } = {}) => {
    const lineas = await refrescar();
    return (full ? lineas : lineas.slice(0, 120)).join("\n");
  },
  fill: async (id, valor) => {
    await page.fill(await aSelector(id), String(valor));
    await refrescar();
  },
  click: async (id) => {
    await page.click(await aSelector(id));
    await refrescar();
  },
};

try {
  // Los guiones siembran datos con `fetch` desde dentro de la página, así que
  // hace falta estar en el origen de la app: desde `about:blank` no hay red.
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  const salida = await guion(page, ui);
  console.log(JSON.stringify(salida, null, 2));
} catch (e) {
  console.log("SNAPSHOT ERROR", e?.stack ?? String(e));
  process.exitCode = 1;
} finally {
  await navegador.close();
}

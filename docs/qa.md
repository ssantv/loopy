# QA de navegador

Cómo se prueba Loopy de verdad, contra la app real y un Chromium de verdad. No hay
mocks: los guiones registran usuarios, siembran tareas y leen lo que se ve.

## Puesta a punto

Tres procesos, y la suite no arranca ninguno:

```bash
# 1. API
cd api
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 2. Frontend (el runner espera esto en :5173)
cd frontend
npm install
npm run dev

# 3. Playwright, solo la primera vez
npm install          # en la raíz del repo
npx playwright-core install chromium
```

La raíz tiene su propio `package.json` y **no** es la app: ahí solo vive la
herramienta de QA. Las dependencias de la app siguen en `frontend/`.

Ojo con el nombre del binario: con `playwright-core` el comando es
`npx playwright-core install chromium`, no `npx playwright install`. El segundo se
trae el paquete entero y duplica lo que ya está instalado.

## Pasadas

```bash
npm run qa          # 16 guiones contra el dev server
npm run qa:build    # 2 guiones contra el build servido
```

Salida `0` solo si todo está en verde. Cualquier guion que devuelva un `false`, un
`{error}` o un código distinto de 0 lo pone a rojo.

Las dos pasadas no se mezclan y no se pueden sustituir. `qa-push-ui.mjs` y
`qa-prueba-session.mjs` necesitan el service worker, y el service worker solo se
registra en producción (ver `frontend/src/registerSW.ts`): contra `npm run dev`
no hay push que probar. Para esa pasada hace falta el build:

```bash
cd frontend
npm run build
npm run preview     # sirve dist en :4173
```

Un detalle que costó tiempo: si reconstruyes mientras el `preview` está sirviendo,
los hashes de los assets cambian bajo sus pies y el navegador se queda sin
ficheros que cargar. Termina el build **antes** de arrancar el preview.

## Un guion suelto

```bash
node docs/qa-suite.mjs --solo=home        # subconjunto por nombre
node docs/qa-suite.mjs --verbose          # con los volcados de pantalla
python docs/qa_run.py -- node docs/qa-driver.mjs http://localhost:5173 --script docs/qa-home.mjs
```

Lo de siempre: por encima del envoltorio, las cuentas se quedan en la BD.

## Cómo se escribe un guion

Exporta una función y devuelve un objeto de comprobaciones. Los valores `false` son
fallos; lo que no sea booleano se imprime como contexto.

```js
export default async function run(page, ui) {
  return { apareceElSaludo: true, boton: await ui.snapshot() };
}
```

Y si necesita producción, decláralo, que si no el runner lo dará por bueno sin
llegar a ejecutarlo nunca:

```js
export const necesitaBuild = true;
```

El driver da dos cosas, y `page` de Playwright normal:

- `ui.snapshot({ full })`: líneas `@e12 button "Guardar"`. Cada elemento sale dos
  veces si su texto en el código y su nombre accesible difieren, que es el caso
  normal en MUI con `text-transform: uppercase`. Los dos comparten ref, así que un
  guion puede comparar `"CASA"` o `"Casa"` según lo que quiera afirmar.
- `ui.fill("@e12", "texto")` y `ui.click("@e12")`: operated sobre ese ref.

No se usan selectores a propósito. Los guiones afirman sobre lo que se ve, no
sobre clases de MUI: cuando cambia el estilo el guion sigue valiendo, y cuando
falta un texto en pantalla el guion falla. Es lo contrario de un test que se
rompe cada vez que se toca el markup sin que nada se haya roto.

## Limpieza

`qa_run.py` marca el `users.id` más alto antes de empezar y borra en cascada todo
lo creado después, pase o falle. Cada guion corre dentro de su propio envoltorio,
así que la BD de desarrollo se queda con las cuentas reales.

Si un guion se lanza a pelo, sus cuentas se quedan: se borran a mano con
`SELECT id, email FROM users WHERE email LIKE 'qa_%'`.

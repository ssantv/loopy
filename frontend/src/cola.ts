/**
 * Cola de escrituras para cuando no hay red.
 *
 * Solo entra aquí lo que el usuario ha decidido de verdad y el servidor todavía no
 * sabe: marcar un deber como hecho, deshacerlo, y colocar o quitar una tarea de un
 * hueco. Todo lo demás sigue fallando si no hay red, a propósito. Una app donde
 * "guardar" significa a veces "guardar", a veces "guardar luego" y a veces "guardar si
 * el servidor deja de responder" hace que la gente deje de fiarse del botón.
 *
 * Por qué IndexedDB y no `localStorage`: la cola tiene que sobrevivir a que se cierre
 * la pestaña, y `localStorage` no tiene forma de avisar de que un registro se ha
 * estropeado ni admite nada asíncrono. `localStorage` además es de strings, así que
 * aquí se acabarían guardando JSON a mano.
 *
 * El orden importa y no se reordena nada: si sin red se marca una tarea como hecha y
 * acto seguido se deshace, la cola tiene que mandar los dos en ese orden para que al
 * final el servidor diga lo mismo que dice la pantalla. Si se colapsara a "el último
 * gana", un fallo en medio dejaría la tarea como hecha sin haberlo pedido nadie.
 */

const BD = "loopy-cola";
const ALMACEN = "escrituras";
const VERSION = 1;
/**
 * Tope de la cola.
 *
 * Es un tope de seguridad, no de diseño: si alguien deja la app abierta sin red un día
 * entero, la idea es que avise y deje de encolar, no que se quede comiendo el
 * almacenamiento del móvil. Con este tope entran de sobra las acciones de un día de
 * cole, que es para lo que está pensada.
 */
const MAX_ESCRITURAS = 200;

export type Metodo = "POST" | "DELETE";

export interface Escritura {
  /** Único, y además el que ordena la cola. */
  id: string;
  metodo: Metodo;
  /** Ruta relativa, tal cual la usa `request` (`/api/tasks/12/place`). */
  ruta: string;
  /** Cuerpo JSON ya serializado, o `null` en los `DELETE`. */
  cuerpo: string | null;
  /** Milisegundos. Se usa para mandar antes lo más viejo. */
  creada: number;
  intentos: number;
  /** Última razón por la que no se pudo mandar, para poder explicarla. */
  ultimoError?: string;
}

export interface Conflicto {
  /** Lo que se quiso hacer, para poder contarlo en sus términos. */
  descripcion: string;
  /** Lo que dijo el servidor. */
  motivo: string;
}

export interface ResumenDrenado {
  enviadas: number;
  conflictos: Conflicto[];
  /** `true` si se paró porque no hay red: lo que queda sigue en la cola. */
  sinRed: boolean;
  /** `true` si se paró por un error del servidor, para reintentar más tarde. */
  reintentable: boolean;
}

/**
 * Cómo ha acabado una de las cuatro escrituras que pueden ir a la cola.
 *
 * Tres estados y no un "sí/no" a propósito. Con un booleano, "lo ha guardado el
 * servidor" y "no se ha podido guardar en ningún sitio" acabarían igual, porque las
 * dos devuelven `encolada: false`. La diferencia es justo la que importa: la primera
 * es invisible para el usuario, la segunda es una acción suya que se pierde. Con esta
 * unión, quien llama no puede confundirlas por accidente.
 */
export type EstadoEscritura<T> =
  | { estado: "guardada"; valor: T }
  /** Quedó en la cola y se mandará al volver la red. */
  | { estado: "encolada" }
  /** Ni se ha mandado ni se ha podido guardar: hay que avisar al usuario. */
  | { estado: "fallo"; valor: T | null };

// El reloj del envío lo pone quien lo llama, no la cola: un `POST` que se queda
// esperando para siempre bloquea la cola entera detrás de él, y eso lo sabe mejor
// `request`, que es quien tiene el `AbortController`.
type Enviar = (metodo: Metodo, ruta: string, cuerpo: string | null) => Promise<void>;

let enviar: Enviar | null = null;

/**
 * El que sabe cómo hablar con el servidor se lo inyecta quien lo tiene.
 *
 * La cola no importa nada de `client.ts` para poder importarlo sin ciclo, y así se
 * puede probar sin red. Es el mismo detalle que hace `request` dueño del token.
 */
export function definirEnvio(fn: Enviar): void {
  enviar = fn;
}

let contador = 0;

function nuevoId(): string {
  contador += 1;
  const aleatorio = Math.random().toString(36).slice(2, 8);
  return `${Date.now().toString(36)}-${contador.toString(36)}-${aleatorio}`;
}

// ------------------------------------------------------------------- almacenamiento

/**
 * La base de datos, o `null` si el navegador no la da.
 *
 * Puede faltar en modo privado de algunos navegadores, y también si el usuario tiene
 * bloqueado el almacenamiento. No es un caso raro, así que se comprueba una vez y se
 * sigue trabajando: si no hay cola, las escrituras sin red fallan con su error
 * normal, que es un fallo honesto y visible.
 */
let promesaBd: Promise<IDBDatabase | null> | null = null;

function abrirBd(): Promise<IDBDatabase | null> {
  if (promesaBd) return promesaBd;
  promesaBd = new Promise((resolve) => {
    if (typeof indexedDB === "undefined") {
      resolve(null);
      return;
    }
    let peticion: IDBOpenDBRequest;
    try {
      peticion = indexedDB.open(BD, VERSION);
    } catch {
      resolve(null);
      return;
    }
    peticion.onupgradeneeded = () => {
      const db = peticion.result;
      if (!db.objectStoreNames.contains(ALMACEN)) {
        // El `id` es la clave, y como es un número de milisegundos con un contador
        // detrás, recorrer el almacén ya sale en orden y no hace falta ni un índice.
        db.createObjectStore(ALMACEN, { keyPath: "id" });
      }
    };
    peticion.onsuccess = () => resolve(peticion.result);
    // Un `onerror` sin esto se queda la promesa esperando para siempre, y con ella
    // toda la app: es el fallo silencioso más caro que se puede tener aquí.
    peticion.onerror = () => resolve(null);
    peticion.onblocked = () => resolve(null);
  });
  return promesaBd;
}

function transaccion(db: IDBDatabase, modo: IDBTransactionMode): IDBObjectStore {
  return db.transaction(ALMACEN, modo).objectStore(ALMACEN);
}

function espera<T>(peticion: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    peticion.onsuccess = () => resolve(peticion.result);
    peticion.onerror = () => reject(peticion.error);
  });
}

export async function disponible(): Promise<boolean> {
  return (await abrirBd()) !== null;
}

export async function listar(): Promise<Escritura[]> {
  const db = await abrirBd();
  if (!db) return [];
  const todas = await espera(transaccion(db, "readonly").getAll() as IDBRequest<Escritura[]>);
  return todas.sort((a, b) => a.creada - b.creada || a.id.localeCompare(b.id));
}

async function poner(escritura: Escritura): Promise<void> {
  const db = await abrirBd();
  if (!db) throw new Error("no hay almacenamiento para la cola");
  await espera(transaccion(db, "readwrite").put(escritura) as IDBRequest<IDBValidKey>);
}

async function quitar(id: string): Promise<void> {
  const db = await abrirBd();
  if (!db) return;
  await espera(transaccion(db, "readwrite").delete(id) as IDBRequest<undefined>);
}

async function tocar(escritura: Escritura): Promise<void> {
  await poner(escritura);
}

export async function vaciar(): Promise<void> {
  const db = await abrirBd();
  if (!db) return;
  await espera(transaccion(db, "readwrite").clear() as IDBRequest<undefined>);
}

// ------------------------------------------------------------------- encolar

/**
 * Encola una escritura. Devuelve si pudo.
 *
 * Si no puede (sin IndexedDB, o cola llena) devuelve `false` en vez de lanzar: quien
 * llama lo trata como "no se ha podido guardar" y lo enseña, que es lo que hay que
 * hacer. Lo contrario sería tragarse el fallo y perder la acción sin avisar.
 */
export async function encolar(metodo: Metodo, ruta: string, cuerpo: string | null): Promise<boolean> {
  const db = await abrirBd();
  if (!db) return false;
  const existentes = await espera(transaccion(db, "readonly").count() as IDBRequest<number>);
  if (existentes >= MAX_ESCRITURAS) return false;
  await poner({ id: nuevoId(), metodo, ruta, cuerpo, creada: Date.now(), intentos: 0 });
  avisar();
  return true;
}

// ------------------------------------------------------------------- avisar a la UI

type Oyente = (escrituras: Escritura[]) => void;
const oyentes = new Set<Oyente>();

/**
 * Quién quiere enterarse de cómo quedan las cosas.
 *
 * La UI necesita saber cuántas cosas hay pendientes y avisar de los conflictos, así
 * que hay alguien escuchando en todo momento. Se avisa también al encolar, no solo al
 * mandar, para que el contador suba en el acto.
 */
export function alCambiar(oyente: Oyente): () => void {
  oyentes.add(oyente);
  void listar().then(oyente).catch(() => {});
  return () => {
    oyentes.delete(oyente);
  };
}

function avisar(): void {
  void listar().then((escrituras) => {
    for (const oyente of oyentes) oyente(escrituras);
  });
}

// ------------------------------------------------------------------- mandar

/**
 * Un fallo de red: no se ha podido ni preguntar. Se distingue del resto porque la
 * cola debe **parar** y no tirar la escritura, que no está mal: solo no se pudo ahora.
 */
function esFaltaDeRed(e: unknown): boolean {
  return e instanceof Error && e.name === "OfflineError";
}

function estadoDe(e: unknown): number {
  return typeof e === "object" && e !== null && "status" in e ? Number((e as { status: number }).status) : 0;
}

/**
 * El servidor ha dicho que no. Gana el servidor, como se decidió: la escritura se
 * tira y se cuenta como conflicto para avisar, en vez de reintentarla para siempre.
 *
 * Los `4xx` que se quedan fuera a propósito son el `401` (la sesión ya no vale: si se
 * reintentara, cada pendientes fallaría por lo mismo y no avanzaría nada) y el `429`
 * (demasiados intentos: ahora no es el momento).
 */
function esConflicto(e: unknown): boolean {
  const estado = estadoDe(e);
  return estado >= 400 && estado < 500 && estado !== 401 && estado !== 429;
}

let drenando: Promise<ResumenDrenado> | null = null;

/**
 * Manda todo lo que se pueda, en orden, y se para en cuanto algo va mal.
 *
 * Parar es la parte importante. Si el servidor está caído y la cola sigue mandando,
 * cada escritura tarda en fallar y se gastan los treinta segundos de reloj una detrás
 * de otra; y si la red se fue a medias, lo que queda por detrás tampoco tiene a dónde
 * ir. Mandar una a una, parar y reintentar después es más lento en el caso bueno y
 * infinitamente más rápido en el malo.
 *
 * Dos llamadas a la vez comparten la promesa: si llega la red y además se llama al
 * montar la app, sin esto se mandaría cada escritura dos veces.
 */
export function drenar(): Promise<ResumenDrenado> {
  if (drenando) return drenando;
  drenando = drenarAhora().finally(() => {
    drenando = null;
  });
  return drenando;
}

async function drenarAhora(): Promise<ResumenDrenado> {
  const resumen: ResumenDrenado = { enviadas: 0, conflictos: [], sinRed: false, reintentable: false };
  if (!enviar) return resumen;
  // `navigator.onLine` solo dice que hay interfaz, no que haya internet. Sirve como
  // atajo para no perder medio minuto esperando en el metro, y como aviso de que
  // ahora mismo no va a pasar nada; si dice que sí y no hay red, el error del envío
  // es quien se encarga de parar.
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    return { ...resumen, sinRed: true };
  }

  const pendientes = await listar();
  for (const escritura of pendientes) {
    try {
      await enviar(escritura.metodo, escritura.ruta, escritura.cuerpo);
    } catch (e) {
      if (esFaltaDeRed(e)) {
        // Se deja en la cola y se para: no ha pasado nada malo, solo faltaba red.
        return { ...resumen, sinRed: true };
      }
      if (esConflicto(e)) {
        await quitar(escritura.id);
        resumen.conflictos.push({
          descripcion: describir(escritura),
          motivo: e instanceof Error ? e.message : "el servidor no lo aceptó",
        });
        avisar();
        continue;
      }
      // Un 5xx o algo raro: no se tira nada, se apunta el último error y se para. La
      // escritura se reintentará, y el error sirve para explicar por qué sigue ahí.
      await tocar({
        ...escritura,
        intentos: escritura.intentos + 1,
        ultimoError: e instanceof Error ? e.message : String(e),
      });
      avisar();
      return { ...resumen, reintentable: true };
    }
    await quitar(escritura.id);
    resumen.enviadas += 1;
  }

  if (resumen.enviadas || resumen.conflictos.length) avisar();
  return resumen;
}

/**
 * Traduce la escritura a algo que se pueda contar en una frase.
 *
 * Los ids no le dicen nada a nadie: "el servidor no aceptó la escritura 7" no es un
 * aviso, es un ruido. Con la ruta y el método ya se entiende qué se quiso hacer.
 */
function describir(escritura: Escritura): string {
  const partes = escritura.ruta.split("/").filter(Boolean);
  const recurso = partes[partes.length - 1] ?? "";
  if (escritura.ruta.endsWith("/place")) {
    return escritura.metodo === "DELETE" ? "quitar una tarea de su rato" : "colocar una tarea en un hueco";
  }
  if (escritura.ruta.includes("/complete")) {
    return escritura.metodo === "DELETE" ? "deshacer una tarea" : "marcar una tarea como hecha";
  }
  return `${escritura.metodo} ${recurso}`;
}

// ------------------------------------------------------------------- usar la cola

/**
 * `request`, pero sin red no lanza: encola y avisa de lo que pasó.
 *
 * Solo para las cuatro escrituras que se ha decidido. Devolver `guardada` con un
 * `valor: null` cuando queda en la cola no es un atajo, es la honestidad de decir que
 * no hay respuesta de servidor porque no se ha preguntado a nadie. Cualquier otro
 * fallo sí se propaga: si el servidor contesta con un `401`, con un `429` o con un
 * error de verdad, eso no es falta de red y hay que tratarlo como lo que es.
 *
 * El caso raro es el tercero: sin red y sin IndexedDB. No es tan raro como parece
 * (modo privado, almacenamiento bloqueado, cola llena) y es el peor de los tres
 * porque la acción del usuario se pierde sin más. Se devuelve `fallo` en vez de
 * tragárselo, para que la pantalla pueda decirlo en voz alta.
 */
export async function escribir<T>(metodo: Metodo, ruta: string, cuerpo: unknown): Promise<EstadoEscritura<T>> {
  if (!enviar) throw new Error("la cola no tiene a quién preguntar");
  let cuerpoJson: string | null;
  try {
    cuerpoJson = cuerpo === undefined ? null : JSON.stringify(cuerpo);
  } catch (e) {
    // Un cuerpo que no se puede serializar no es un problema de red: es un fallo de
    // quien llama, y dejarlo pasar a la cola solo lo convierte en un error que
    // aparecerá días después sin explicación.
    throw new Error("no se ha podido preparar el cambio: " + (e instanceof Error ? e.message : String(e)));
  }
  try {
    await enviar(metodo, ruta, cuerpoJson);
    return { estado: "guardada", valor: null as T };
  } catch (e) {
    if (!esFaltaDeRed(e)) throw e;
  }
  const dentro = await encolar(metodo, ruta, cuerpoJson);
  return dentro ? { estado: "encolada" } : { estado: "fallo", valor: null };
}
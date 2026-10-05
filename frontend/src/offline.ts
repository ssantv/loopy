/**
 * Constantes compartidas entre la página y el service worker.
 *
 * Vite compila `sw.ts` en un bundle aparte, pero los dos importan desde aquí, y por eso
 * los nombres de las cachés viven en un solo sitio: si se escribieran en los dos
 * archivos, un cambio en uno dejaría la app leyendo de una caché que la otra no llena,
 * y el síntoma sería "funciona sin conexión a veces" sin explicación posible.
 */

/**
 * Las lecturas del servidor.
 *
 * El prefijo importa: es lo que permite vaciar **solo** las lecturas cuando alguien
 * escribe, sin tirar el app shell. Un `caches.keys()` a secas se llevaría por delante
 * también el precache, y la app dejaría de arrancar sin conexión hasta la siguiente
 * visita con red.
 */
export const CACHE_LECTURAS = "loopy-lecturas-v1";

/**
 * Cuánto tiempo se guarda una lectura antes de tirar la más antigua.
 *
 * Sin tope, una cuenta que mire mucho la app acumula el día entero de respuestas, cada
 * una con los datos de una familia entera. Cuarenta entradas es de sobra para el
 * uso normal y acotado en memoria en un móvil viejo, que es donde duele.
 */
export const MAX_ENTRADAS_LECTURAS = 40;

/**
 * Cuánto se espera a la red antes de enseñar lo que hay en caché.
 *
 * Tres segundos es el punto donde la espera se nota como "va lento" pero todavía no se
 * nota como "no funciona". Con `NetworkFirst` puro, una conexión de móvil que no
 * contesta deja la pantalla en blanco indefinidamente, que es la peor forma de fallar.
 */
export const SEGUNDOS_ANTES_DE_CACHE = 3;

/**
 * Cuánto espera la app a una respuesta antes de darse por perdida.
 *
 * Deliberadamente generoso: hay endpoints que piden una recomendación y tardan. Y
 * ninguna petición va con este reloj si quien la llama le pasa su propio `signal`.
 */
export const SEGUNDOS_TIMEOUT = 30;
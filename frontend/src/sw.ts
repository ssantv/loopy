/// <reference lib="webworker" />
import { precacheAndRoute, createHandlerBoundToURL } from "workbox-precaching";
import { registerRoute, NavigationRoute } from "workbox-routing";
import { NetworkFirst } from "workbox-strategies";
import { CacheableResponsePlugin } from "workbox-cacheable-response";
import { ExpirationPlugin } from "workbox-expiration";
import { clientsClaim } from "workbox-core";
import { CACHE_LECTURAS, MAX_ENTRADAS_LECTURAS, SEGUNDOS_ANTES_DE_CACHE } from "./offline";

declare let self: ServiceWorkerGlobalScope;

/**
 * El manifiesto, leído una sola vez y de una sola manera.
 *
 * `workbox-build` sustituye el texto `self.__WB_MANIFEST` por el array literal, y
 * exige que aparezca exactamente una vez: si se repite, la build falla con un
 * `AssertionError` en vez de avisar de nada útil. Guardarlo aquí deja ese único
 * punto de sustitución y permite usarlo las veces que haga falta.
 */
const MANIFEST = self.__WB_MANIFEST;

precacheAndRoute(MANIFEST);
self.skipWaiting();
clientsClaim();

/**
 * El índice del precache, buscado por nombre en vez de escrito a mano.
 *
 * La URL puede llegar como "index.html" o como "/index.html" según la base y la
 * versión del plugin, y `createHandlerBoundToURL` necesita la misma cadena que se usó
 * al rellenar el precache. Escribirla a mano era una forma de tener un service worker
 * que compilaba, se registraba, no daba ningún error... y no resolvía nunca.
 *
 * El manifiesto se tipa como entradas `string | PrecacheEntry`, así que una entrada
 * puede venir como string pelado: en ese caso se usa tal cual.
 */
function urlDelShell(): string {
  for (const entrada of MANIFEST) {
    const url = typeof entrada === "string" ? entrada : entrada.url;
    if (url.endsWith("index.html")) return url;
  }
  return "index.html";
}

/**
 * Las navegaciones se resuelven con el shell, nunca con la red.
 *
 * Sin esto, abrir `/colegio` sin conexión da un error de red del navegador: no es un
 * 404 de la app, es que ni se llega a preguntar. La expansión de `precacheAndRoute`
 * solo prueba `/colegio` y `/colegio.html`, y en el precache está `index.html`, así
 * que el acierto no ocurría solo. Con esta ruta, cualquier ruta de la SPA se sirve
 * del shell y luego React Router decide qué pantalla es, que es lo que sabe hacer.
 */
registerRoute(new NavigationRoute(createHandlerBoundToURL(urlDelShell())));

/**
 * Las lecturas del servidor: primero la red, y si no contesta, lo último que se leyó.
 *
 * "Primero la red" es lo correcto y no una casualidad: la app enseña datos que
 * cambian (qué toca hoy, el menú, la compra), y quedarse con lo viejo un día entero
 * sería peor que no tener nada. El límite de tres segundos es lo que evita que una
 * red que no contesta deje la pantalla en blanco.
 *
 * Solo `GET`. Una escritura cacheada sería una mentira: el usuario marcaría algo como
 * hecho y recargaría, y lo que volvería sería lo que el servidor dice, no lo que él
 * cree. Eso no lo arregla una caché, lo arregla una cola, y es otro trabajo.
 */
registerRoute(
  ({ url, request }) => url.origin === self.location.origin && url.pathname.startsWith("/api/") && request.method === "GET",
  new NetworkFirst({
    cacheName: CACHE_LECTURAS,
    networkTimeoutSeconds: SEGUNDOS_ANTES_DE_CACHE,
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      new ExpirationPlugin({
        maxEntries: MAX_ENTRADAS_LECTURAS,
        // Sin `purgeOnQuotaError` se puede llenar el almacenamiento sin poder escribir,
        // y la app sin poder cachear: la peor combinación posible en un móvil con el
        // disco lleno. Con esto, Workbox tira lo viejo cuando no cabe.
        purgeOnQuotaError: true,
      }),
    ],
  }),
);

/**
 * Raíz de caché que se invalida al escribir en `url`.
 *
 * Se agrupa por los dos primeros segmentos (`/api/tasks/12/place` -> `/api/tasks`)
 * porque en este backend una escritura siempre convive con la lista del mismo
 * recurso: al marcar un deber hay que volver a pedir la lista de deberes, y esa
 * respuesta es la que se tiene que tirar. Invalidar solo la URL exacta dejaría
 * sirviendo una lista vieja justo después de haber escrito, y la app enseñaría que no
 * se guardó.
 */
function raizDeLaUrl(url: URL): string {
  const partes = url.pathname.split("/").filter(Boolean);
  return "/" + partes.slice(0, 2).join("/");
}

/**
 * Las escrituras: no se cachean, pero avisan de lo que dejan viejo.
 *
 * Este es el detalle que hace que "leer sin conexión" no rompa "escribir con red". Sin
 * él, escribir una tarea y recargar a ciegas podría devolver la lista de antes, y el
 * usuario perdería la confianza en la app por un fallo de caché y no de servidor.
 */
async function purgarLoViejo(raiz: string): Promise<void> {
  const cache = await caches.open(CACHE_LECTURAS);
  for (const req of await cache.keys()) {
    const url = new URL(req.url);
    if (url.origin === self.location.origin && url.pathname.startsWith(raiz + "/")) {
      await cache.delete(req);
    }
  }
}

registerRoute(
  ({ url, request }) => url.origin === self.location.origin && url.pathname.startsWith("/api/") && request.method !== "GET",
  async ({ request, url }) => {
    const respuesta = await fetch(request);
    // Solo se purga lo que esta escritura deja viejo. No se avisa a las ventanas
    // abiertas ni se recarga nada: la pantalla que acaba de escribir ya se refresca
    // sola, y recargarle por detrás se comería un formulario a medio escribir o la
    // posición de la lista. Las lecturas siguientes salen de la red de todas formas,
    // porque la estrategia es "primero la red".
    if (respuesta.ok) await purgarLoViejo(raizDeLaUrl(url));
    return respuesta;
  },
);

interface PushPayload {
  title?: string;
  body?: string;
  url?: string;
}

self.addEventListener("push", (event) => {
  let data: PushPayload = { title: "Loopy" };
  if (event.data) {
    try {
      data = event.data.json() as PushPayload;
    } catch {
      data = { title: "Loopy", body: event.data.text() };
    }
  }
  const payload: PushPayload = { url: "/", ...data };
  event.waitUntil(
    self.registration.showNotification(payload.title ?? "Loopy", {
      body: payload.body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url: payload.url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url: string = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if ("focus" in client) {
          client.navigate?.(url);
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
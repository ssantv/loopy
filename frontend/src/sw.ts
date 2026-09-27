/// <reference lib="webworker" />
import { precacheAndRoute } from "workbox-precaching";
import { clientsClaim } from "workbox-core";

declare let self: ServiceWorkerGlobalScope;

precacheAndRoute(self.__WB_MANIFEST);

self.skipWaiting();
clientsClaim();

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      await self.clients.claim();
      const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const c of clients) {
        c.navigate?.(new URL(c.url).pathname + new URL(c.url).search);
      }
    })(),
  );
});

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
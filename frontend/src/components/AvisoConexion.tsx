import { useCallback, useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import WifiOffIcon from "@mui/icons-material/WifiOff";
import CloudQueueIcon from "@mui/icons-material/CloudQueue";
import { alCambiar, drenar, listar, type Escritura } from "../cola";

/** Primer intento tras un fallo del servidor, en milisegundos. */
const ESPACIO_REINTENTO = 15_000;
/** Tope de la espera, para no dejar de intentarlo nunca ni esperar diez minutos. */
const ESPERA_MAXIMA = 90_000;

/**
 * Los tres estados que hay que distinguir, y por qué en este orden.
 *
 * 1. No hay red. Antes decía "no se puede guardar nada nuevo", y era verdad, pero
 *    empujaba a la gente a no intentarlo. Ahora se puede seguir marcando.
 * 2. Hay red pero hay cambios esperando. La cola puede tener cosas pendientes aun
 *    teniendo red, porque el servidor estaba caído cuando se hicieron. Se enseña
 *    cuántas y hay un botón, sin recargar.
 * 3. El servidor ha dicho que no. Cuando un `4xx` tumba una escritura, gana el
 *    servidor, como se decidió: se descarta y **se avisa**. Es el único caso en que
 *    se pierde algo que el usuario hizo, así que tiene que verse.
 *
 * Lo que no hace, a propósito: recargar. La tentación vuelve con la cola y el motivo
 * es el mismo de antes, más fuerte: ahora la recarga puede caer en mitad de un
 * formulario y perder además la posición de lo que se está mandando.
 */
export function AvisoConexion() {
  const [sinRed, setSinRed] = useState(() => typeof navigator !== "undefined" && !navigator.onLine);
  const [pendientes, setPendientes] = useState<Escritura[]>([]);
  const [rechazados, setRechazados] = useState<string[]>([]);
  const [mandando, setMandando] = useState(false);
  const reintento = useRef<number | null>(null);

  /**
   * Manda lo que haya y cuenta lo que pasó.
   *
   * Está en un sitio solo porque los dos caminos (el automático al volver la red y el
   * botón "Enviar") tienen que hacer exactamente lo mismo. Si el botón se olvidara de
   * avisar de los conflictos, el usuario vería como enviado algo que el servidor
   * rechazó, que es justo el fallo que hace que la gente deje de fiarse de la cola.
   *
   * Si el servidor contesta `5xx`, `drenar` deja la cola donde está y avisa con
   * `reintentable`. Aquí se programa otro intento: sin red, el evento `online` llega
   * solo, pero un servidor caído con la interfaz encendida no dispara nada, y lo que se
   * quedaría es una cola que no se manda nunca hasta que el usuario cierre la app. El
   * plazo se dobla a cada intento hasta un minuto y medio, para no castigar a un
   * servidor que ya está cayendo de por sí.
   */
  const mandarCola = useCallback(async () => {
    const resumen = await drenar();
    if (resumen.enviadas) {
      // Lo que se ve en pantalla puede venir de un pintado optimista, así que quien
      // esté escuchando tiene la palabra: recarguen lo suyo y comprobarán que el
      // servidor dice lo mismo. Con un evento y no un `reload()`, porque recargar
      // tira la posición de donde esté el usuario.
      window.dispatchEvent(new CustomEvent("loopy:datos-guardados"));
    }
    if (resumen.conflictos.length) {
      setRechazados(resumen.conflictos.map((c) => `${c.descripcion}: ${c.motivo}`));
    }
    if (reintento.current !== null) {
      window.clearTimeout(reintento.current);
      reintento.current = null;
    }
    if (resumen.reintentable) {
      const intentos = await listar().then((p) => p.reduce((n, e) => Math.max(n, e.intentos), 0));
      const espera = Math.min(ESPACIO_REINTENTO * 2 ** intentos, ESPERA_MAXIMA);
      reintento.current = window.setTimeout(() => {
        reintento.current = null;
        void mandarCola();
      }, espera);
    }
    return resumen;
  }, []);

  // `online` pone `sinRed` a false y manda la cola; `offline` solo avisa. Cada uno
  // hace una cosa: con un solo manejador para los dos se acabaría mandando la cola
  // dos veces, o no se pondría el aviso nunca.
  useEffect(() => {
    const alPerder = () => setSinRed(true);
    window.addEventListener("offline", alPerder);
    return () => window.removeEventListener("offline", alPerder);
  }, []);

  // La cola manda sola al volver la red. Se hace aquí y no en la app porque este
  // componente está montado siempre que hay sesión, y porque el `online` es lo único
  // que de verdad significa "ahora sí hay red" (y no solo "hay interfaz").
  useEffect(() => {
    const alVolver = () => {
      setSinRed(false);
      void mandarCola();
    };
    window.addEventListener("online", alVolver);
    // También al montar: la app puede haberse abierto con la cola llena de ayer, o
    // haber recuperado la red mientras estaba dormida y nadie se enteró.
    if (navigator.onLine) alVolver();
    return () => {
      window.removeEventListener("online", alVolver);
      // El temporizador de reintento es de este componente y no de la cola: sin esta
      // limpieza, al navegar a otra página se queda vivo y manda escrituras sin que
      // haya nadie mirando, que es justo lo que no queremos.
      if (reintento.current !== null) window.clearTimeout(reintento.current);
      reintento.current = null;
    };
  }, [mandarCola]);

  useEffect(() => alCambiar(setPendientes), []);

  const mandarAhora = useCallback(async () => {
    setMandando(true);
    try {
      await mandarCola();
    } finally {
      setMandando(false);
    }
  }, [mandarCola]);

  if (rechazados.length > 0) {
    return (
      <Box sx={{ px: 2, pt: 1 }}>
        <Alert severity="error" onClose={() => setRechazados([])} data-testid="aviso-rechazado">
          No se ha podido guardar {rechazados.length === 1 ? "un cambio" : `${rechazados.length} cambios`}:{" "}
          {rechazados.join("; ")}. Se ha mantenido lo que dice el servidor.
        </Alert>
      </Box>
    );
  }

  if (!sinRed && pendientes.length === 0) return null;

  return (
    <Box sx={{ px: 2, pt: 1 }}>
      <Stack spacing={1}>
        {sinRed && (
          <Alert severity="warning" icon={<WifiOffIcon />} data-testid="aviso-sin-conexion">
            Sin conexión. Se ven los últimos datos que se leyeron. Puedes seguir marcando tareas: se
            guardarán solas al volver la red.
          </Alert>
        )}
        {pendientes.length > 0 && (
          <Alert
            severity="info"
            icon={<CloudQueueIcon />}
            data-testid="aviso-pendientes"
            // El botón solo con red: sin ella el envío no puede hacer nada, y dejarlo ahí
            // tapando el contador con un botón que no hace nada es peor que no ofrecerlo.
            action={
              sinRed || mandando ? undefined : (
                <Button color="inherit" size="small" onClick={() => void mandarAhora()}>
                  {mandando ? "Enviando" : "Enviar"}
                </Button>
              )
            }
          >
            {pendientes.length === 1 ? "Hay 1 cambio sin enviar." : `Hay ${pendientes.length} cambios sin enviar.`}{" "}
            {sinRed ? "Se mandarán solos al volver la red." : "Se mandarán solos."}
          </Alert>
        )}
      </Stack>
    </Box>
  );
}
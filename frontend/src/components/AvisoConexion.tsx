import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import WifiOffIcon from "@mui/icons-material/WifiOff";

/**
 * Aviso de que no hay red.
 *
 * Se avisa solo cuando el navegador dice que no hay red, no cuando una llamada falla.
 * La diferencia importa: un fallo puntual puede ser el servidor, y un aviso de "sin
 * conexión" por culpa del servidor enseña a desconfiar del indicador. `navigator.onLine`
 * no sabe si la red sirve internet de verdad, solo si hay interfaz, así que se toma
 * como lo que es: una pista para no fingir que todo va bien.
 *
 * No dispara ninguna recarga al recuperar la red. Podría, y sería un error: lo que se
 * enseñó mientras no había red sale de la caché del service worker, y al volver lo
 * natural es que la siguiente lectura se refresque sola, que es lo que ya hace la
 * estrategia "primero la red". Forzar un `location.reload()` aquí se comería un
 * formulario a medio escribir o la posición de la lista, y solo para ahorrar unos segundos.
 */
export function AvisoConexion() {
  const [sinRed, setSinRed] = useState(() => typeof navigator !== "undefined" && !navigator.onLine);

  useEffect(() => {
    const alCambiar = () => setSinRed(!navigator.onLine);
    window.addEventListener("online", alCambiar);
    window.addEventListener("offline", alCambiar);
    return () => {
      window.removeEventListener("online", alCambiar);
      window.removeEventListener("offline", alCambiar);
    };
  }, []);

  if (!sinRed) return null;
  return (
    <Box sx={{ px: 2, pt: 1 }}>
      <Alert severity="warning" icon={<WifiOffIcon />} data-testid="aviso-sin-conexion">
        Sin conexión. Se ven los últimos datos que se leyeron, y no se puede guardar nada nuevo.
      </Alert>
    </Box>
  );
}
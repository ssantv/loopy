import { useState } from "react";
import Alert from "@mui/material/Alert";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Button from "@mui/material/Button";
import NotificationsIcon from "@mui/icons-material/Notifications";
import NotificationsOffIcon from "@mui/icons-material/NotificationsOff";
import { taskApi } from "../api/client";

// El backend guarda `due_at` como reloj de pared (notify.py lo combina con el día
// de la tarea y solo lee la parte de hora), así que lo que se manda es la fecha del
// día que tocará más la hora elegida, sin zona: mandarlo con `Z` convertiría la hora
// al_devices timezone y el aviso saltaría a una hora que el usuario no escribió.
const HORA_POR_DEFECTO = "18:00";

function horaDe(dueAt: string | null): string {
  if (!dueAt) return HORA_POR_DEFECTO;
  // `2026-10-05T18:00:00` → `18:00`. Con offset o `Z` el substring 11..16 sigue
  // siendo la hora tal como la escribió el usuario, que es lo que se quiere mostrar.
  return dueAt.slice(11, 16) || HORA_POR_DEFECTO;
}

/**
 * Interruptor de "avísame a esta hora" para una tarea.
 *
 * Existe porque `Task.notify` y `Task.due_at` están en el modelo, la API los acepta
 * y el scheduler los encola, pero no había forma de activarlos desde la app: el
 * recordatorio solo se podía provocar llamando a la API a mano.
 *
 * Apagarlo manda solo `notify: false` porque el PATCH descarta los `null`
 * (routers/tasks.py), así que la hora se queda guardada. Es inocuo: el scheduler
 * exige las dos cosas a la vez.
 */
export default function ReminderToggle({
  id,
  dia,
  notify,
  dueAt,
  avisadoPorPush,
  onChanged,
  onError,
}: {
  id: number;
  /** Día en el que saltaría el aviso; el scheduler lo combina con la hora. */
  dia: string;
  notify: boolean;
  dueAt: string | null;
  /** Si el usuario tiene push suscrito: sin esto, el aviso no llega. */
  avisadoPorPush: boolean;
  onChanged: (t: { id: number; notify: boolean; due_at: string | null }) => void;
  onError: (m: string) => void;
}) {
  const [editando, setEditando] = useState(false);
  const [hora, setHora] = useState(() => horaDe(dueAt));
  const [guardando, setGuardando] = useState(false);

  const activo = notify && !!dueAt;

  const apagar = async () => {
    try {
      const t = await taskApi.update(id, { notify: false });
      onChanged({ id: t.id, notify: t.notify, due_at: t.due_at });
      setEditando(false);
    } catch (e) {
      onError(e instanceof Error ? e.message : "No se pudo quitar el aviso");
    }
  };

  const guardar = async () => {
    if (!hora) return;
    setGuardando(true);
    try {
      const t = await taskApi.update(id, { notify: true, due_at: `${dia}T${hora}:00` });
      onChanged({ id: t.id, notify: t.notify, due_at: t.due_at });
      setEditando(false);
    } catch (e) {
      onError(e instanceof Error ? e.message : "No se pudo activar el aviso");
    } finally {
      setGuardando(false);
    }
  };

  if (!editando) {
    const etiqueta = activo ? `Quitar el aviso de las ${horaDe(dueAt)}` : `Avisarme a una hora`;
    return (
      <Tooltip title={etiqueta}>
        <IconButton
          size="small"
          // Nombre explícito: el icono no tiene texto y sin esto un lector de
          // pantalla anuncia solo "botón".
          aria-label={etiqueta}
          onClick={() => (activo ? void apagar() : setEditando(true))}
          sx={{ color: activo ? "primary.main" : "text.disabled" }}
        >
          {activo ? <NotificationsIcon fontSize="inherit" /> : <NotificationsOffIcon fontSize="inherit" />}
        </IconButton>
      </Tooltip>
    );
  }

  return (
    <Stack direction="row" spacing={1} alignItems="center" sx={{ px: 1, pb: 1, flexWrap: "wrap" }}>
      <TextField
        label="Avisarme a las"
        type="time"
        size="small"
        value={hora}
        onChange={(ev) => setHora(ev.target.value)}
        slotProps={{ inputLabel: { shrink: true } }}
      />
      <Button size="small" variant="contained" onClick={() => void guardar()} disabled={!hora || guardando}>
        Guardar
      </Button>
      <Button size="small" onClick={() => setEditando(false)} disabled={guardando}>
        Cancelar
      </Button>
      {!avisadoPorPush && (
        <Alert severity="warning" sx={{ width: "100%", py: 0 }}>
          Aún no has activado los avisos del móvil: se guardará, pero no te llegará nada hasta suscribirte en Mi día.
        </Alert>
      )}
    </Stack>
  );
}
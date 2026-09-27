import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { pendingApi, type Task } from "../api/client";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import Chip from "@mui/material/Chip";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";

const CATEGORY_LABEL: Record<string, string> = {
  general: "General",
  hogar: "Hogar",
  "colegio-deberes": "Deberes",
  "colegio-trabajo": "Trabajo",
  puntual: "Cosa de hoy",
};

const CATEGORY_COLOR: Record<string, string> = {
  general: "#757575",
  hogar: "#8d6e63",
  "colegio-deberes": "#0288d1",
  "colegio-trabajo": "#7b1fa2",
  puntual: "#ef6c00",
};

function fmtDate(d: string): string {
  return new Date(d + "T00:00:00").toLocaleDateString("es-ES", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

function Row({
  task,
  checked,
  onToggle,
}: {
  task: Task;
  checked: boolean;
  onToggle: (task: Task) => void;
}) {
  return (
    <ListItem disablePadding sx={{ mb: 0.5, bgcolor: "background.paper", border: 1, borderColor: "divider" }}>
      <ListItemButton onClick={() => onToggle(task)} sx={{ borderRadius: 2 }}>
        <Checkbox edge="start" checked={checked} tabIndex={-1} disableRipple readOnly />
        <ListItemText
          primary={
            <Stack direction="row" spacing={1} alignItems="center" component="span">
              <Typography>{task.title}</Typography>
              <Chip
                label={CATEGORY_LABEL[task.category] ?? task.category}
                size="small"
                sx={{ bgcolor: CATEGORY_COLOR[task.category] ?? "#757575", color: "#fff", height: 20 }}
                component="span"
              />
            </Stack>
          }
          secondary={
            task.pending && task.pending < todayISO() ? (
              <Typography variant="caption" color="error">
                Desde el {fmtDate(task.pending)}
              </Typography>
            ) : null
          }
        />
      </ListItemButton>
    </ListItem>
  );
}

function todayISO(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export default function Pendientes() {
  const [pending, setPending] = useState<{ overdue: Task[]; today: Task[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPending(await pendingApi.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar pendientes");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const allIds = useMemo(() => {
    if (!pending) return [];
    return [...pending.overdue, ...pending.today].map((t) => t.id);
  }, [pending]);

  const toggle = useCallback((task: Task) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(task.id)) next.delete(task.id);
      else next.add(task.id);
      return next;
    });
  }, []);

  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id));

  const toggleAll = useCallback(() => {
    setSelected(allSelected ? new Set() : new Set(allIds));
  }, [allSelected, allIds]);

  const completeSelected = useCallback(async () => {
    if (selected.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const res = await pendingApi.complete([...selected]);
      setMsg(
        res.errors.length > 0
          ? `Completadas: ${res.completed.length}, con errores: ${res.errors.length}`
          : `¡Bien! ${res.completed.length} tarea${res.completed.length === 1 ? "" : "s"} al día.`,
      );
      setSelected(new Set());
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al completar");
    } finally {
      setBusy(false);
    }
  }, [load, selected]);

  const count = allIds.length;
  const sections: { title: string; tasks: Task[] }[] = [];
  if (pending) {
    if (pending.overdue.length > 0) sections.push({ title: "Atrasadas", tasks: pending.overdue });
    if (pending.today.length > 0) sections.push({ title: "Para hoy", tasks: pending.today });
  }

  return (
    <Box>
      <AppBar position="static">
        <Toolbar sx={{ gap: 1 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Pendientes
          </Typography>
          <Button color="inherit" size="small" component={Link} to="/">
            Mi día
          </Button>
        </Toolbar>
      </AppBar>

      <Box sx={{ maxWidth: 640, margin: "0 auto", padding: "1.5rem 1rem" }}>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}
        {msg && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMsg(null)}>
            {msg}
          </Alert>
        )}

        {loading ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
            <CircularProgress />
          </Box>
        ) : count === 0 ? (
          <Alert severity="success" sx={{ borderRadius: 2 }}>
            No tienes nada pendiente. Todo al día.
          </Alert>
        ) : (
          <Stack spacing={3}>
            <Stack direction="row" spacing={2} alignItems="center">
              <Typography color="text.secondary" sx={{ flexGrow: 1 }}>
                {count} tarea{count === 1 ? "" : "s"} pendiente{count === 1 ? "" : "s"} ·{" "}
                {selected.size} marcada{selected.size === 1 ? "" : "s"}
              </Typography>
              <Button size="small" onClick={toggleAll}>
                {allSelected ? "Ninguna" : "Todas"}
              </Button>
              <Button
                variant="contained"
                size="small"
                disabled={selected.size === 0 || busy}
                onClick={() => void completeSelected()}
              >
                Completar ({selected.size})
              </Button>
            </Stack>

            {sections.map((s) => (
              <section key={s.title}>
                <Typography variant="h6" sx={{ mb: 1 }}>
                  {s.title}
                </Typography>
                <List sx={{ p: 0 }}>
                  {s.tasks.map((t) => (
                    <Row key={t.id} task={t} checked={selected.has(t.id)} onToggle={toggle} />
                  ))}
                </List>
              </section>
            ))}
          </Stack>
        )}
      </Box>
    </Box>
  );
}
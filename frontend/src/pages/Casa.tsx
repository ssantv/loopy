import { useCallback, useEffect, useMemo, useState } from "react";
import { BOTTOM_BAR_PADDING, PageNav, SubNav } from "../components/Nav";
import ReminderToggle from "../components/ReminderToggle";
import { homeApi, pushApi, roomApi, taskApi, type HomeItem, type HomeOut, type Room } from "../api/client";
import { todayISO } from "./today";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import ListItemSecondaryAction from "@mui/material/ListItemSecondaryAction";
import Chip from "@mui/material/Chip";
import Collapse from "@mui/material/Collapse";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import IconButton from "@mui/material/IconButton";
import DeleteIcon from "@mui/icons-material/Delete";

const CATEGORY_LABEL: Record<string, string> = {
  general: "General",
  hogar: "Hogar",
  puntual: "Cosa de hoy",
};

function fmtDay(d: string | null): string {
  if (!d) return "";
  const date = new Date(d + "T00:00:00");
  return date.toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" });
}

/** Devuelve la lista con la tarea actualizada, para no tener que recargar la página. */
function aplicar(items: HomeItem[], t: { id: number; notify: boolean; due_at: string | null }): HomeItem[] {
  return items.map((i) => (i.id === t.id ? { ...i, notify: t.notify, due_at: t.due_at } : i));
}

export default function Casa() {
  const today = todayISO();
  const [home, setHome] = useState<HomeOut | null>(null);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState(0);
  const [openAhead, setOpenAhead] = useState<Record<string, boolean>>({});
  // El aviso solo llega si el usuario está suscrito al push. Preguntarlo es
  // barato (un GET) y evita el "yo lo activé y no me llegó nada".
  const [pushListo, setPushListo] = useState(true);

  // Formulario de nueva tarea
  const [newTitle, setNewTitle] = useState("");
  const [newCategory, setNewCategory] = useState<string>("hogar");
  const [newRoom, setNewRoom] = useState<number>(0);
  const [newDate, setNewDate] = useState<string>(todayISO());

  // Formulario de habitación
  const [newRoomName, setNewRoomName] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [h, r] = await Promise.all([homeApi.get(today), roomApi.list()]);
      setHome(h);
      setRooms(r);
      setNewRoom((cur) => (cur === 0 && r.length > 0 ? r[0].id : cur));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar el hogar");
    } finally {
      setLoading(false);
    }
  }, [today]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    // `segment === "subscribed"` es lo único que importa; si el push no está
    // configurado en el servidor, `enabled` sale false y no hay nada que avise.
    pushApi
      .config()
      .then((c) => setPushListo(c.enabled && c.segment === "subscribed"))
      .catch(() => setPushListo(false));
  }, []);

  const trasCambiarAviso = useCallback(
    (t: { id: number; notify: boolean; due_at: string | null }) => {
      setHome((h) =>
        h
          ? {
              ...h,
              rooms: h.rooms.map((r) => ({ ...r, pending: aplicar(r.pending, t), ahead: aplicar(r.ahead, t) })),
              no_room: { ...h.no_room, pending: aplicar(h.no_room.pending, t), ahead: aplicar(h.no_room.ahead, t) },
            }
          : h,
      );
    },
    [],
  );

  const toggleToday = useCallback(
    async (item: HomeItem) => {
      try {
        if (item.done.includes(today)) {
          await taskApi.undo(item.id, today);
        } else {
          await taskApi.complete(item.id, today);
        }
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al actualizar la tarea");
      }
    },
    [today, load],
  );

  const advance = useCallback(
    async (item: HomeItem) => {
      try {
        await taskApi.advance(item.id);
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al adelantar la tarea");
      }
    },
    [load],
  );

  const addTask = useCallback(async () => {
    const title = newTitle.trim();
    if (!title) return;
    try {
      await taskApi.create({
        title,
        category: newCategory,
        room_id: newCategory === "hogar" && newRoom ? newRoom : null,
        due_on: newDate || null,
      });
      setNewTitle("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al crear la tarea");
    }
  }, [newTitle, newCategory, newRoom, newDate, load]);

  const addRoom = useCallback(async () => {
    const name = newRoomName.trim();
    if (!name) return;
    try {
      await roomApi.create({ name });
      setNewRoomName("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al crear la habitación");
    }
  }, [newRoomName, load]);

  const flatPending = useMemo(() => {
    if (!home) return [] as HomeItem[];
    const items = home.rooms.flatMap((r) => r.pending).concat(home.no_room.pending);
    return items;
  }, [home]);

  const pendingCount = useMemo(() => {
    return flatPending.length;
  }, [flatPending]);

  const allAhead = useMemo(() => {
    if (!home) return [] as HomeItem[];
    return home.rooms.flatMap((r) => r.ahead).concat(home.no_room.ahead);
  }, [home]);

  const dayLabel = useMemo(
    () => new Date(today + "T00:00:00").toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" }),
    [today],
  );

  if (loading && !home) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  const roomCards = home
    ? home.rooms.map((r) => {
        const aheadKey = String(r.id);
        return (
          <Box key={r.id} sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.5 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Box sx={{ width: 12, height: 12, borderRadius: 6, bgcolor: r.color ?? "#9e9e9e" }} />
              <Typography variant="h6">{r.name}</Typography>
              <Typography variant="caption" color="text.secondary">
                ({r.pending.length} pendientes)
              </Typography>
            </Stack>
            <TaskCheckList
              items={r.pending}
              doneToday={today}
              onToggle={toggleToday}
              pushListo={pushListo}
              onReminderChanged={trasCambiarAviso}
              onError={setError}
            />
            {r.ahead.length > 0 && (
              <Box>
                <Button
                  fullWidth
                  size="small"
                  onClick={() => setOpenAhead((o) => ({ ...o, [aheadKey]: !o[aheadKey] }))}
                  sx={{ justifyContent: "space-between", textTransform: "none" }}
                >
                  <span>Adelantadas ({r.ahead.length})</span>
                  <span>{openAhead[aheadKey] ? "▴" : "▾"}</span>
                </Button>
                <Collapse in={!!openAhead[aheadKey]}>
                  <TaskAdvanceList items={r.ahead} onAdvance={advance} />
                </Collapse>
              </Box>
            )}
          </Box>
        );
      })
    : null;

  return (
    <Box>
      <PageNav title="Casa" />

      <Box sx={{ maxWidth: 640, margin: "0 auto", padding: "1.5rem 1rem", pb: BOTTOM_BAR_PADDING }}>
        <SubNav area="casa" />
        <Typography variant="h4">Casa</Typography>
        <Typography color="text.secondary" sx={{ textTransform: "capitalize", mb: 2 }}>
          {dayLabel}
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Stack spacing={3}>
          <section>
            <Typography variant="h6" sx={{ mb: 1 }}>
              Nueva tarea
            </Typography>
            <Stack spacing={1}>
              <TextField
                size="small"
                placeholder="Título de la tarea"
                value={newTitle}
                onChange={(ev) => setNewTitle(ev.target.value)}
                onKeyDown={(ev) => {
                  if (ev.key === "Enter") void addTask();
                }}
              />
              <Stack direction="row" spacing={1}>
                <TextField
                  select
                  size="small"
                  label="Tipo"
                  value={newCategory}
                  onChange={(ev) => setNewCategory(ev.target.value)}
                  sx={{ minWidth: 160 }}
                >
                  <MenuItem value="hogar">Tarea de casa</MenuItem>
                  <MenuItem value="general">General</MenuItem>
                  <MenuItem value="puntual">Cosa de hoy</MenuItem>
                </TextField>
                {newCategory === "hogar" && (
                  <TextField
                    select
                    size="small"
                    label="Habitación"
                    value={newRoom}
                    onChange={(ev) => setNewRoom(Number(ev.target.value))}
                    sx={{ flexGrow: 1 }}
                  >
                    {rooms.map((r) => (
                      <MenuItem key={r.id} value={r.id}>
                        {r.name}
                      </MenuItem>
                    ))}
                  </TextField>
                )}
                <TextField
                  size="small"
                  label="Día"
                  type="date"
                  value={newDate}
                  onChange={(ev) => setNewDate(ev.target.value)}
                />
                <Button variant="contained" onClick={() => void addTask()} disabled={!newTitle.trim()}>
                  Añadir
                </Button>
              </Stack>
            </Stack>
          </section>

          <Tabs value={tab} onChange={(_, v) => setTab(v)}>
            <Tab label={`Por habitaciones (${pendingCount})`} />
            <Tab label="Todas" />
          </Tabs>

          {tab === 0 ? (
            <Stack spacing={2}>
              {roomCards}
              {home && home.no_room.pending.length + home.no_room.ahead.length > 0 && (
                <Box sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.5 }}>
                  <Typography variant="h6" sx={{ mb: 1 }}>
                    Sin habitación
                  </Typography>
                  <TaskCheckList
                items={home.no_room.pending}
                doneToday={today}
                onToggle={toggleToday}
                pushListo={pushListo}
                onReminderChanged={trasCambiarAviso}
                onError={setError}
              />
                  {home.no_room.ahead.length > 0 && (
                    <Box>
                      <Button
                        fullWidth
                        size="small"
                        onClick={() => setOpenAhead((o) => ({ ...o, __none: !o.__none }))}
                        sx={{ justifyContent: "space-between", textTransform: "none" }}
                      >
                        <span>Adelantadas ({home.no_room.ahead.length})</span>
                        <span>{openAhead.__none ? "▴" : "▾"}</span>
                      </Button>
                      <Collapse in={!!openAhead.__none}>
                        <TaskAdvanceList items={home.no_room.ahead} onAdvance={advance} />
                      </Collapse>
                    </Box>
                  )}
                </Box>
              )}
              {home && home.rooms.length === 0 && (
                <Alert severity="info" sx={{ borderRadius: 2 }}>
                  Añade tu primera habitación (cocina, baño…) y unta ahí las tareas del hogar.
                </Alert>
              )}
            </Stack>
          ) : (
            <Stack spacing={2}>
              <Box sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.5 }}>
                <Typography variant="h6" sx={{ mb: 1 }}>
                  Hoy ({flatPending.length})
                </Typography>
                {flatPending.length === 0 ? (
                  <Alert severity="success" sx={{ borderRadius: 2 }}>
                    Nada pendiente hoy.
                  </Alert>
                ) : (
                  <TaskCheckList
                    items={flatPending}
                    doneToday={today}
                    onToggle={toggleToday}
                    pushListo={pushListo}
                    onReminderChanged={trasCambiarAviso}
                    onError={setError}
                  />
                )}
              </Box>
              {allAhead.length > 0 && (
                <Box sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.5 }}>
                  <Typography variant="h6" sx={{ mb: 1 }}>
                    Adelantadas ({allAhead.length})
                  </Typography>
                  <TaskAdvanceList items={allAhead} onAdvance={advance} />
                </Box>
              )}
            </Stack>
          )}

          <section>
            <Typography variant="h6" sx={{ mb: 1 }}>
              Habitaciones
            </Typography>
            <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
              <TextField
                size="small"
                placeholder="Nueva habitación"
                value={newRoomName}
                onChange={(ev) => setNewRoomName(ev.target.value)}
                onKeyDown={(ev) => {
                  if (ev.key === "Enter") void addRoom();
                }}
                sx={{ flexGrow: 1 }}
              />
              <Button variant="contained" onClick={() => void addRoom()} disabled={!newRoomName.trim()}>
                Añadir
              </Button>
            </Stack>
            <List sx={{ p: 0 }}>
              {rooms.map((r) => (
                <ListItem
                  key={r.id}
                  sx={{ border: 1, borderColor: "divider", borderRadius: 2, mb: 0.5 }}
                >
                  <Box sx={{ width: 12, height: 12, borderRadius: 6, mr: 1, bgcolor: r.color ?? "#9e9e9e" }} />
                  <ListItemText primary={r.name} />
                  <ListItemSecondaryAction>
                    <IconButton
                      edge="end"
                      size="small"
                      onClick={() => {
                        void roomApi
                          .remove(r.id)
                          .then(load)
                          .catch((e: unknown) => setError(e instanceof Error ? e.message : "Error"));
                      }}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </ListItemSecondaryAction>
                </ListItem>
              ))}
            </List>
          </section>
        </Stack>
      </Box>
    </Box>
  );
}

function TaskCheckList({
  items,
  doneToday,
  onToggle,
  pushListo,
  onReminderChanged,
  onError,
}: {
  items: HomeItem[];
  doneToday: string;
  onToggle: (item: HomeItem) => Promise<void>;
  pushListo: boolean;
  onReminderChanged: (t: { id: number; notify: boolean; due_at: string | null }) => void;
  onError: (m: string) => void;
}) {
  if (items.length === 0) return <Alert severity="info" sx={{ borderRadius: 2 }}>Nada pendiente aquí.</Alert>;
  return (
    <List sx={{ p: 0 }}>
      {items.map((item) => {
        const doneOn = item.pending ?? doneToday;
        const done = item.done.includes(doneOn);
        return (
          <ListItem key={item.id} disablePadding sx={{ mb: 0.5 }}>
            <ListItemButton onClick={() => void onToggle(item)} sx={{ borderRadius: 2, border: 1, borderColor: "divider" }}>
              <Checkbox edge="start" checked={done} tabIndex={-1} disableRipple readOnly />
              <ListItemText
                primary={
                  <Typography sx={{ textDecoration: done ? "line-through" : "none" }}>{item.title}</Typography>
                }
                secondary={
                  <Stack direction="row" spacing={1} component="span">
                    <Chip
                      label={CATEGORY_LABEL[item.category] ?? item.category}
                      size="small"
                      sx={{ height: 20 }}
                      component="span"
                    />
                    {item.est_minutes ? (
                      <Typography component="span" variant="caption" color="text.secondary">
                        ~{item.est_minutes} min
                      </Typography>
                    ) : null}
                  </Stack>
                }
              />
            </ListItemButton>
            <ReminderToggle
              id={item.id}
              dia={doneOn}
              notify={item.notify}
              dueAt={item.due_at}
              avisadoPorPush={pushListo}
              onChanged={onReminderChanged}
              onError={onError}
            />
          </ListItem>
        );
      })}
    </List>
  );
}

function TaskAdvanceList({ items, onAdvance }: { items: HomeItem[]; onAdvance: (item: HomeItem) => Promise<void> }) {
  if (items.length === 0) return null;
  return (
    <List sx={{ p: 0 }}>
      {items.map((item) => (
        <ListItem key={item.id} disablePadding sx={{ mb: 0.5 }}>
          <ListItemButton onClick={() => void onAdvance(item)} sx={{ borderRadius: 2, border: 1, borderColor: "divider", bgcolor: "action.hover" }}>
            <Checkbox edge="start" checked={false} tabIndex={-1} disableRipple readOnly />
            <ListItemText
              primary={
                <Stack direction="row" spacing={1} alignItems="center" component="span">
                  <Typography>{item.title}</Typography>
                </Stack>
              }
              secondary={
                <Typography variant="caption" color="text.secondary">
                  Haré hoy la de {fmtDay(item.next_on)} → siguiente tras hoy
                </Typography>
              }
            />
          </ListItemButton>
        </ListItem>
      ))}
    </List>
  );
}
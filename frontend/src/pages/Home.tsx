import { useCallback, useEffect, useMemo, useState } from "react";
import { BOTTOM_BAR_PADDING, PageNav, useIsChild } from "../components/Nav";
import {
  taskApi,
  pendingApi,
  pushApi,
  urlBase64ToUint8Array,
  subjectApi,
  type Exam,
  type Task,
  examApi,
  type PlanItem,
  type PlanPhase,
  type Subject,
} from "../api/client";
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
import Divider from "@mui/material/Divider";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import type { SxProps } from "@mui/material/styles";

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

const PHASE_LABEL: Record<string, string> = {
  resumen: "Resumen",
  estudio: "Estudio",
  practica: "Práctica",
  repaso: "Repaso",
  "repaso-final": "Repaso final",
};

const PHASE_COLOR: Record<string, string> = {
  resumen: "#0288d1",
  estudio: "#2e7d32",
  practica: "#7b1fa2",
  repaso: "#ef6c00",
  "repaso-final": "#d32f2f",
};

function fmtDate(d: string): string {
  const date = new Date(d + "T00:00:00");
  return date.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
}

function todayISO(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseDay(d: string): Date {
  return new Date(d + "T00:00:00");
}

function daysBetween(fromISO: string, toISO: string): number {
  return Math.round((parseDay(toISO).getTime() - parseDay(fromISO).getTime()) / 86400000);
}

function fmtShortDate(d: string): string {
  return parseDay(d).toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" });
}

function countdownLabel(targetISO: string, today: string, noun: string): string {
  const diff = daysBetween(today, targetISO);
  if (diff === 0) return `¡${noun} es hoy!`;
  if (diff === 1) return `${noun} mañana`;
  return `${noun} en ${diff} días`;
}

const SCHOOL_CATEGORIES = ["colegio-deberes", "colegio-trabajo"];

function toTaskState(task: Task, today: string): "hoy" | "hecho" | "atrasada" | "adelantada" | null {
  if (task.done.includes(today)) return "hecho";
  if (task.due_on && !task.rec_type) {
    if (task.due_on === today) return "hoy";
    if (task.due_on < today && !task.done.includes(task.due_on)) return "atrasada";
    return null;
  }
  if (task.rec_type) {
    if (!task.pending) return null;
    if (task.pending === today) return "hoy";
    if (task.pending < today) return "atrasada";
    return "adelantada";
  }
  return null;
}

export default function Home() {
  const isChild = useIsChild();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [examPlanItems, setExamPlanItems] = useState<{ item: PlanItem; subject: string; examId: number }[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [exams, setExams] = useState<Exam[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [atrasadasOpen, setAtrasadasOpen] = useState(false);
  const [adelantadasOpen, setAdelantadasOpen] = useState(false);
  const [hechoOpen, setHechoOpen] = useState(false);
  const [sessionOpen, setSessionOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);

  const today = useMemo(todayISO, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
    let examItems: { item: PlanItem; subject: string; examId: number }[] = [];
    let subjectRows: Subject[] = [];
    let examRows: Exam[] = [];
      if (isChild) {
      subjectRows = await subjectApi.list();
      examRows = await examApi.list();
      for (const ex of examRows) {
        if (ex.exam_date >= today) {
          const plan = await examApi.plan(ex.id, today, today);
          examItems.push(...plan.items.map((item) => ({ item, subject: plan.subject.name, examId: ex.id })));
        }
      }
    }
    const [tasksResult] = await Promise.all([taskApi.list(today), Promise.resolve(examItems)]);
    setTasks(tasksResult);
    setExamPlanItems(examItems);
    setSubjects(subjectRows);
    setExams(examRows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar tareas");
    } finally {
      setLoading(false);
    }
  }, [today, isChild]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo(() => {
    const hoy: Task[] = [];
    const hecho: Task[] = [];
    const atrasadas: Task[] = [];
    const adelantadas: Task[] = [];
    for (const t of tasks) {
      const st = toTaskState(t, today);
      if (st === "hoy") hoy.push(t);
      else if (st === "hecho") hecho.push(t);
      else if (st === "atrasada") atrasadas.push(t);
      else if (st === "adelantada") adelantadas.push(t);
    }
    const bySort = (a: Task, b: Task) => a.sort - b.sort || a.created_at.localeCompare(b.created_at);
    return { hoy: hoy.sort(bySort), hecho: hecho.sort(bySort), atrasadas: atrasadas.sort(bySort), adelantadas: adelantadas.sort(bySort) };
  }, [tasks, today]);

  // Deberes/trabajos de colegio aún no hechos. Excluye los de hoy, que ya
  // aparecen arriba en "Qué toca hoy", para no repetir la misma línea.
  const colegio = useMemo(() => {
    const hoyIds = new Set(groups.hoy.map((t) => t.id));
    return tasks
      .filter((t) => SCHOOL_CATEGORIES.includes(t.category))
      .filter((t) => !hoyIds.has(t.id))
      .filter((t) => toTaskState(t, today) !== "hecho")
      .sort((a, b) => (a.due_on ?? "9999").localeCompare(b.due_on ?? "9999") || a.sort - b.sort);
  }, [tasks, today, groups.hoy]);

  const proximosExamenes = useMemo(() => {
    return exams
      .filter((e) => e.exam_date >= today)
      .sort((a, b) => a.exam_date.localeCompare(b.exam_date))
      .slice(0, 4);
  }, [exams, today]);

  const toggle = useCallback(
    async (task: Task, doneOn: string) => {
      const isDone = task.done.includes(doneOn);
      try {
        if (isDone) {
          await taskApi.undo(task.id, doneOn);
        } else {
          await taskApi.complete(task.id, doneOn);
        }
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al actualizar la tarea");
      }
    },
    [load],
  );

  const togglePlan = useCallback(
    async (examId: number, item: PlanItem) => {
      const isDone = item.status === "done";
      try {
        if (isDone) {
          await examApi.undoPlanItem(examId, item.date);
        } else {
          await examApi.markPlanItem(examId, item.date, "done");
        }
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al actualizar el estudio");
      }
    },
    [load],
  );

  const addSession = useCallback(
    async (subjectId: number, phase: PlanPhase) => {
      try {
        await subjectApi.addSession(subjectId, { date: today, phase });
        setSessionOpen(false);
        void load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al registrar la sesión");
      }
    },
    [today, load],
  );

  const completeAllToday = useCallback(async () => {
    const ids = groups.hoy.map((t) => t.id);
    if (ids.length === 0) return;
    setBulkBusy(true);
    setBulkMsg(null);
    try {
      const res = await pendingApi.complete(ids);
      setBulkMsg(
        res.errors.length > 0
          ? `Completadas: ${res.completed.length}, con errores: ${res.errors.length}`
          : `¡Bien! ${res.completed.length} tarea${res.completed.length === 1 ? "" : "s"} al día.`,
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al completar");
    } finally {
      setBulkBusy(false);
    }
  }, [groups.hoy, load]);

  const listItemSx: SxProps = { borderRadius: 2 };

  return (
    <Box>
      <PageNav title="Mi día" />

      <Box sx={{ maxWidth: 640, margin: "0 auto", padding: "1.5rem 1rem", pb: BOTTOM_BAR_PADDING }}>
        <Typography variant="h4" sx={{ mb: 0.5 }}>
          Hola{isChild ? " pequeño" : ""}
        </Typography>
        <Typography color="text.secondary" sx={{ textTransform: "capitalize", mb: 2 }}>
          {fmtDate(today)}
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {loading ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
            <CircularProgress />
          </Box>
        ) : (
          <Stack spacing={3}>
            <section>
              <Typography variant="h6" sx={{ mb: 1 }}>
                Qué toca hoy
              </Typography>
              {groups.hoy.length === 0 && examPlanItems.length === 0 ? (
                <Alert severity="success" sx={{ borderRadius: 2 }}>
                  No tienes nada pendiente para hoy.
                </Alert>
              ) : (
                <>
                  <List sx={{ p: 0 }}>
                  {groups.hoy.map((t) => (
                    <TaskRow key={t.id} task={t} today={today} onToggle={toggle} sx={listItemSx} />
                  ))}
                  {examPlanItems.map(({ item, subject, examId }) => (
                    <ExamPlanRow
                      key={`${item.date}-${item.phase}`}
                      item={item}
                      subject={subject}
                      onToggle={() => void togglePlan(examId, item)}
                    />
                  ))}
                  {isChild && subjects.length > 0 && (
                    <Box sx={{ mt: 1 }}>
                      <Button variant="outlined" size="small" onClick={() => setSessionOpen(true)} fullWidth>
                        + Hoy he hecho sesión por mi cuenta
                      </Button>
                    </Box>
                  )}
                  </List>
                  {groups.hoy.length > 0 && (
                    <Box sx={{ mt: 1 }}>
                      <Button
                        variant="outlined"
                        size="small"
                        onClick={() => void completeAllToday()}
                        disabled={bulkBusy}
                        fullWidth
                      >
                        Marcar todo lo de hoy como hecho
                      </Button>
                      {bulkMsg ? (
                        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
                          {bulkMsg}
                        </Typography>
                      ) : null}
                    </Box>
                  )}
                </>
              )}
            </section>

            {groups.hecho.length > 0 && (
              <section>
                <Divider sx={{ mb: 1 }} />
                <Button
                  fullWidth
                  onClick={() => setHechoOpen((v) => !v)}
                  sx={{ justifyContent: "space-between", textTransform: "none" }}
                >
                  <span>✓ Hecho hoy ({groups.hecho.length})</span>
                  <span>{hechoOpen ? "▴" : "▾"}</span>
                </Button>
                <Collapse in={hechoOpen}>
                  <List sx={{ p: 0 }}>
                    {groups.hecho.map((t) => (
                      <TaskRow key={t.id} task={t} today={today} onToggle={toggle} sx={listItemSx} done />
                    ))}
                  </List>
                </Collapse>
              </section>
            )}

            {groups.atrasadas.length > 0 && (
              <section>
                <Button
                  fullWidth
                  onClick={() => setAtrasadasOpen((v) => !v)}
                  color="error"
                  sx={{ justifyContent: "space-between", textTransform: "none" }}
                >
                  <span>⚠ {groups.atrasadas.length} atrasadas</span>
                  <span>{atrasadasOpen ? "▴" : "▾"}</span>
                </Button>
                <Collapse in={atrasadasOpen}>
                  <List sx={{ p: 0 }}>
                    {groups.atrasadas.map((t) => (
                      <TaskRow key={t.id} task={t} today={today} onToggle={toggle} sx={listItemSx} muted />
                    ))}
                  </List>
                </Collapse>
              </section>
            )}

            {groups.adelantadas.length > 0 && (
              <section>
                <Divider sx={{ mb: 1 }} />
                <Button
                  fullWidth
                  onClick={() => setAdelantadasOpen((v) => !v)}
                  sx={{ justifyContent: "space-between", textTransform: "none" }}
                >
                  <span>Adelantadas ({groups.adelantadas.length})</span>
                  <span>{adelantadasOpen ? "▴" : "▾"}</span>
                </Button>
                <Collapse in={adelantadasOpen}>
                  <List sx={{ p: 0 }}>
                    {groups.adelantadas.map((t) => (
                      <TaskRow key={t.id} task={t} today={today} onToggle={toggle} sx={listItemSx} muted />
                    ))}
                  </List>
                </Collapse>
              </section>
            )}

            {isChild && (
              <>
                <section>
                  <Divider sx={{ mb: 1 }} />
                  <Typography variant="h6" sx={{ mb: 1 }}>
                    Próximos exámenes
                  </Typography>
                  {proximosExamenes.length === 0 ? (
                    <Alert severity="info" sx={{ borderRadius: 2 }}>
                      No hay exámenes previstos. Pídele a un adulto que añada uno en Colegio.
                    </Alert>
                  ) : (
                    <List sx={{ p: 0 }}>
                      {proximosExamenes.map((ex) => {
                        const done = ex.exam_date < today;
                        return (
                          <ListItem key={ex.id} disablePadding sx={{ mb: 0.5 }}>
                            <Box
                              sx={{
                                width: "100%",
                                border: 1,
                                borderColor: ex.exam_date === today ? "error.main" : "divider",
                                borderRadius: 2,
                                px: 1.5,
                                py: 1,
                                display: "flex",
                                alignItems: "center",
                                gap: 1,
                                flexWrap: "wrap",
                              }}
                            >
                              <Typography sx={{ fontWeight: 600 }}>{ex.subject_name ?? "Examen"}</Typography>
                              <Chip
                                size="small"
                                label={countdownLabel(ex.exam_date, today, "Examen")}
                                sx={{
                                  bgcolor: done ? "#9e9e9e" : ex.exam_date === today ? "error.main" : "primary.main",
                                  color: "#fff",
                                  height: 22,
                                }}
                              />
                              <Typography variant="body2" color="text.secondary" sx={{ ml: "auto" }}>
                                {fmtShortDate(ex.exam_date)}
                              </Typography>
                            </Box>
                          </ListItem>
                        );
                      })}
                    </List>
                  )}
                </section>

                {colegio.length > 0 && (
                  <section>
                    <Divider sx={{ mb: 1 }} />
                    <Typography variant="h6" sx={{ mb: 1 }}>
                      Deberes y trabajos ({colegio.length})
                    </Typography>
                    <List sx={{ p: 0 }}>
                      {colegio.map((t) => (
                        <TaskRow
                          key={t.id}
                          task={t}
                          today={today}
                          onToggle={toggle}
                          sx={listItemSx}
                          dueLabel={t.due_on ? countdownLabel(t.due_on, today, "Entrega") : "Sin fecha"}
                          overdue={!!t.due_on && t.due_on < today}
                        />
                      ))}
                    </List>
                  </section>
                )}
              </>
            )}

            <PushSection />
          </Stack>
        )}
      </Box>

      <SessionDialog
        open={sessionOpen}
        subjects={subjects}
        onClose={() => setSessionOpen(false)}
        onAdd={(subjectId, phase) => void addSession(subjectId, phase)}
      />
    </Box>
  );
}

function SessionDialog({
  open,
  subjects,
  onClose,
  onAdd,
}: {
  open: boolean;
  subjects: Subject[];
  onClose: () => void;
  onAdd: (subjectId: number, phase: PlanPhase) => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Adelantar sesión</DialogTitle>
      <DialogContent>
        {subjects.length === 0 ? (
          <Typography color="text.secondary">No hay asignaturas todavía.</Typography>
        ) : (
          <Stack spacing={1.5}>
            <Typography variant="body2" color="text.secondary">
              Registra que has hecho una sesión aunque el plan no la marque hoy.
            </Typography>
            {subjects.map((s) => (
              <Box
                key={s.id}
                sx={{
                  border: 1,
                  borderColor: "divider",
                  borderRadius: 2,
                  p: 1.5,
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 1,
                  alignItems: "center",
                }}
              >
                <Typography sx={{ flexGrow: 1 }}>{s.name}</Typography>
                {(Object.keys(PHASE_LABEL) as PlanPhase[]).map((ph) => (
                  <Chip
                    key={ph}
                    label={PHASE_LABEL[ph]}
                    size="small"
                    clickable
                    onClick={() => onAdd(s.id, ph)}
                    sx={{ bgcolor: PHASE_COLOR[ph], color: "#fff" }}
                  />
                ))}
              </Box>
            ))}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cerrar</Button>
      </DialogActions>
    </Dialog>
  );
}

function TaskRow({
  task,
  today,
  onToggle,
  sx,
  muted,
  done: doneProp,
  dueLabel,
  overdue,
}: {
  task: Task;
  today: string;
  onToggle: (task: Task, doneOn: string) => Promise<void>;
  sx?: SxProps;
  muted?: boolean;
  done?: boolean;
  dueLabel?: string;
  overdue?: boolean;
}) {
  const doneOn = task.due_on && !task.rec_type ? task.due_on : task.pending ?? today;
  const done = doneProp ?? task.done.includes(doneOn);
  const handle = (e: React.MouseEvent) => {
    e.stopPropagation();
    void onToggle(task, doneOn);
  };
  return (
    <ListItem
      disablePadding
      sx={{
        ...sx,
        mb: 0.5,
        bgcolor: muted ? "action.hover" : "background.paper",
        border: 1,
        borderColor: "divider",
        opacity: done ? 0.6 : 1,
      }}
    >
      <ListItemButton onClick={handle} sx={{ borderRadius: 2 }}>
        <Checkbox edge="start" checked={done} tabIndex={-1} disableRipple readOnly />
        <ListItemText
          primary={
            <Typography sx={{ textDecoration: done ? "line-through" : "none" }}>{task.title}</Typography>
          }
          secondary={
            <Stack direction="row" spacing={1} alignItems="center" component="span">
              <Chip
                label={CATEGORY_LABEL[task.category] ?? task.category}
                size="small"
                sx={{ bgcolor: CATEGORY_COLOR[task.category] ?? "#757575", color: "#fff", height: 20 }}
                component="span"
              />
              {task.est_minutes ? (
                <Typography component="span" variant="caption" color="text.secondary">
                  ~{task.est_minutes} min
                </Typography>
              ) : null}
            </Stack>
          }
        />
      </ListItemButton>
      <ListItemSecondaryAction>
        <Stack direction="row" spacing={0.5} alignItems="center">
          {task.notes ? (
            <Typography variant="caption" color="text.secondary">
              {task.notes}
            </Typography>
          ) : null}
          {dueLabel ? (
            <Chip
              size="small"
              label={dueLabel}
              sx={{
                bgcolor: overdue ? "error.main" : "action.hover",
                color: overdue ? "#fff" : "text.primary",
                height: 20,
              }}
            />
          ) : null}
        </Stack>
      </ListItemSecondaryAction>
    </ListItem>
  );
}

function ExamPlanRow({
  item,
  subject,
  onToggle,
}: {
  item: PlanItem;
  subject: string;
  onToggle: () => void;
}) {
  const done = item.status === "done";
  const skipped = item.status === "skip";
  return (
    <ListItem disablePadding sx={{ mb: 0.5 }}>
      <ListItemButton
        onClick={onToggle}
        sx={{ borderRadius: 2, border: 1, borderColor: "divider", opacity: done ? 0.6 : 1 }}
      >
        <Checkbox
          edge="start"
          checked={done}
          indeterminate={skipped}
          tabIndex={-1}
          disableRipple
          readOnly
        />
        <ListItemText
          primary={subject}
          secondary={
            <Stack direction="row" spacing={1} alignItems="center" component="span">
              <Chip
                label={item.label ?? PHASE_LABEL[item.phase] ?? item.phase}
                size="small"
                sx={{ bgcolor: PHASE_COLOR[item.phase] ?? "#757575", color: "#fff", height: 20 }}
                component="span"
              />
              {done ? (
                <Typography component="span" variant="caption" color="text.secondary">
                  Hecho ✓
                </Typography>
              ) : (
                <Typography component="span" variant="caption" color="text.secondary">
                  Toca hoy
                </Typography>
              )}
            </Stack>
          }
        />
      </ListItemButton>
    </ListItem>
  );
}

function PushSection() {
  const [supported, setSupported] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      setSupported(false);
      return;
    }
    setSupported(true);
    try {
      const cfg = await pushApi.config();
      setEnabled(cfg.enabled);
      setSubscribed(cfg.segment === "subscribed");
    } catch {
      setEnabled(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onSubscribe = useCallback(async () => {
    setBusy(true);
    setMsg(null);
    try {
      const cfg = await pushApi.config();
      if (!cfg.enabled) {
        setMsg("El servidor no tiene push configurado (VAPID).");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const perm = await Notification.requestPermission();
      if (perm !== "granted") {
        setMsg("Permiso denegado: no llegarán notificaciones.");
        return;
      }
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(cfg.public_key),
      });
      await pushApi.subscribe(sub);
      setSubscribed(true);
      setMsg("Suscrito. Prueba el botón de abajo.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "No se pudo suscribir");
    } finally {
      setBusy(false);
    }
  }, []);

  const onTest = useCallback(async () => {
    setBusy(true);
    setMsg(null);
    try {
      await pushApi.test();
      setMsg("Notificación encolada: debería llegar en unos segundos.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "No se pudo encolar");
    } finally {
      setBusy(false);
    }
  }, []);

  const onUnsubscribe = useCallback(async () => {
    setBusy(true);
    setMsg(null);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await pushApi.unsubscribe(sub);
        await sub.unsubscribe();
      }
      setSubscribed(false);
      setMsg("Suscripción cancelada.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "No se pudo cancelar");
    } finally {
      setBusy(false);
    }
  }, []);

  if (!supported) return null;

  return (
    <section>
      <Divider sx={{ mb: 1 }} />
      <Typography variant="h6" sx={{ mb: 1 }}>
        Notificaciones
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Avisos de tareas con hora, check-in del niño y resumen diario.
      </Typography>
      {!enabled ? (
        <Alert severity="info" sx={{ borderRadius: 2 }}>
          Push no configurado en el servidor (VAPID).
        </Alert>
      ) : subscribed ? (
        <Stack spacing={1} direction="row">
          <Button variant="outlined" onClick={() => void onTest()} disabled={busy}>
            Probar notificación
          </Button>
          <Button color="inherit" onClick={() => void onUnsubscribe()} disabled={busy}>
            Desuscribir
          </Button>
        </Stack>
      ) : (
        <Button variant="contained" onClick={() => void onSubscribe()} disabled={busy}>
          Suscribirme a notificaciones
        </Button>
      )}
      {msg && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          {msg}
        </Typography>
      )}
    </section>
  );
}
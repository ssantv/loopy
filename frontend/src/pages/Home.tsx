import { useCallback, useEffect, useMemo, useState } from "react";
import { BOTTOM_BAR_PADDING, PageNav, useIsChild } from "../components/Nav";
import {
  taskApi,
  pendingApi,
  pushApi,
  workSessionApi,
  urlBase64ToUint8Array,
  subjectApi,
  dayLoadApi,
  dayTimelineApi,
  appointmentApi,
  api,
  type DayLoad,
  type DayTimeline,
  type DayBlock,
  type Appointment,
  type AppointmentInput,
  type User,
  type Exam,
  type Task,
  examApi,
  type PlanItem,
  type PlanPhase,
  type Subject,
  type WorkSessionEstimate,
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
import FormControlLabel from "@mui/material/FormControlLabel";
import TextField from "@mui/material/TextField";
import CircularProgress from "@mui/material/CircularProgress";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Divider from "@mui/material/Divider";
import Paper from "@mui/material/Paper";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import { alpha, type SxProps } from "@mui/material/styles";
import CloseIcon from "@mui/icons-material/Close";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";

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

// La cosa con la que empezar la mañana. O una tarea o una sesión del plan de
// estudio de un examen (que se marca aparte, en study_completions).
type Focus =
  | { kind: "task"; task: Task; overdue: boolean }
  | { kind: "plan"; item: PlanItem; subject: string; examId: number };

// Lo que cronometra el temporizador. `kind` habla el vocabulario de
// work_sessions: deberes, estudio, trabajo o una tarea cualquiera.
type TimerTarget = {
  focus: Focus;
  title: string;
  minutos: number;
  kind: string;
  taskId: number | null;
};

const MIN_POR_DEFECTO = 25;

function kindDeCategoria(categoria: string): string {
  if (categoria === "colegio-deberes") return "homework";
  if (categoria === "colegio-trabajo") return "project";
  return "task";
}

function mmss(segundos: number): string {
  return `${Math.floor(segundos / 60)}:${String(segundos % 60).padStart(2, "0")}`;
}

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
  const [timerTarget, setTimerTarget] = useState<TimerTarget | null>(null);
  const [estimacion, setEstimacion] = useState<WorkSessionEstimate | null>(null);
  const [ajustando, setAjustando] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);
  const [carga, setCarga] = useState<DayLoad | null>(null);
  const [timeline, setTimeline] = useState<DayTimeline | null>(null);
  const [citas, setCitas] = useState<Appointment[]>([]);
  const [citaDialog, setCitaDialog] = useState<CitaDialogState | null>(null);
  const [ninos, setNinos] = useState<User[]>([]);

  // Los niños solo hacen falta para poder elegir a quién afecta una cita, y solo
  // se piden si quien mira la pantalla es un adulto: un niño no crea citas.
  useEffect(() => {
    if (isChild) return;
    void api
      .children()
      .then(setNinos)
      .catch(() => setNinos([]));
  }, [isChild]);

  const today = useMemo(todayISO, []);

  // La carga del día va aparte porque la calcula el backend (reparto del plan +
  // ritmo real del temporizador) y falla sin romper la pantalla: si no se puede,
  // Mi día sigue enseñando lo de siempre.
  const loadCarga = useCallback(async () => {
    try {
      setCarga(await dayLoadApi.get(today));
    } catch {
      setCarga(null);
    }
  }, [today]);

  // El timeline y las citas del día van en la misma pasada porque se necesitan los
  // dos para pintar la sección: el bloque dice qué ocupa el rato, y la cita
  // completa es la única que trae `repeats_weekly`, `until` y las notas, que hacen
  // falta para editarla sin perder nada. Si fallara uno, la sección no se enseña
  // antes que el resto de Mi día: es información extra, no el motivo de abrir la app.
  const loadDia = useCallback(async () => {
    try {
      const [tl, cs] = await Promise.all([dayTimelineApi.get(today), appointmentApi.day(today)]);
      setTimeline(tl);
      setCitas(cs);
    } catch {
      setTimeline(null);
      setCitas([]);
    }
  }, [today]);

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
      // La carga se recalcula con cada recarga de la pantalla porque depende de lo
      // mismo que se acaba de cambiar: marcar una tarea como hecha o añadir una
      // sesión de estudio la deja obsoleta si no se vuelve a pedir.
      void loadCarga();
      void loadDia();
    }
  }, [today, isChild, loadCarga, loadDia]);

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

  // Foco del ahora: primero lo de hoy (tareas en su orden, luego el estudio de
  // exámenes); si no hay nada hoy, la atrasada más antigua. Así la mañana
  // empieza con una sola decisión y el resto queda debajo como apoyo.
  const focus = useMemo<Focus | null>(() => {
    if (groups.hoy.length > 0) return { kind: "task", task: groups.hoy[0], overdue: false };
    if (examPlanItems.length > 0) {
      const { item, subject, examId } = examPlanItems[0];
      return { kind: "plan", item, subject, examId };
    }
    const oldest = [...groups.atrasadas].sort(
      (a, b) =>
        (a.due_on ?? a.pending ?? "9999").localeCompare(b.due_on ?? b.pending ?? "9999") ||
        a.sort - b.sort,
    )[0];
    return oldest ? { kind: "task", task: oldest, overdue: true } : null;
  }, [groups, examPlanItems]);

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

  const citasPorId = useMemo(() => new Map(citas.map((c) => [c.id, c])), [citas]);

  const guardarCita = useCallback(
    async (estado: CitaDialogState, cuerpo: AppointmentInput) => {
      try {
        if (estado.cita) await appointmentApi.update(estado.cita.id, cuerpo);
        else await appointmentApi.create(cuerpo);
        setCitaDialog(null);
        // El timeline y la carga comparten los minutos de la cita, así que los dos
        // quedan obsoletos en el mismo instante. Recargar solo uno dejaría la pantalla
        // diciendo dos cosas distintas sobre el mismo día.
        await Promise.all([loadDia(), loadCarga()]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al guardar la cita");
      }
    },
    [loadCarga, loadDia],
  );

  const borrarCita = useCallback(
    async (id: number) => {
      try {
        await appointmentApi.remove(id);
        await Promise.all([loadDia(), loadCarga()]);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al borrar la cita");
      }
    },
    [loadCarga, loadDia],
  );

  const abrirTemporizador = useCallback((focus: Focus) => {
    setTimerTarget({
      focus,
      title:
        focus.kind === "plan"
          ? `${focus.subject} · ${focus.item.label ?? PHASE_LABEL[focus.item.phase] ?? focus.item.phase}`
          : focus.task.title,
      minutos: focus.kind === "plan" ? focus.item.minutes : focus.task.est_minutes ?? 0,
      kind: focus.kind === "plan" ? "study" : kindDeCategoria(focus.task.category),
      taskId: focus.kind === "task" ? focus.task.id : null,
    });
  }, []);

  // El backend solo propone algo cuando hay historial de sobra y la diferencia
  // merece mención; si no, `suggested_minutes` es null y aquí no se pinta nada.
  const claveFoco = focus
    ? focus.kind === "plan"
      ? `plan:${focus.examId}:${focus.item.date}:${focus.item.offset}`
      : `task:${focus.task.id}`
    : "";
  useEffect(() => {
    if (!focus) {
      setEstimacion(null);
      return;
    }
    let vivo = true;
    setEstimacion(null);
    void workSessionApi
      .estimate(
        focus.kind === "plan"
          ? { kind: "study", planned_minutes: focus.item.minutes }
          : { kind: kindDeCategoria(focus.task.category), task_id: focus.task.id },
      )
      .then((est) => {
        if (vivo) setEstimacion(est);
      })
      // Un fallo aquí es cosmético: la tarjeta se queda como estaba.
      .catch(() => {
        if (vivo) setEstimacion(null);
      });
    return () => {
      vivo = false;
    };
  }, [claveFoco, focus]);

  const aplicarEstimacion = useCallback(async () => {
    const minutos = estimacion?.suggested_minutes;
    if (!focus || focus.kind !== "task" || !minutos) return;
    setAjustando(true);
    try {
      const updated = await taskApi.update(focus.task.id, { est_minutes: minutos });
      setTasks((ts) => ts.map((t) => (t.id === updated.id ? updated : t)));
      setEstimacion(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo ajustar la estimación");
    } finally {
      setAjustando(false);
    }
  }, [estimacion, focus]);

  // La sesión se guarda siempre (es trabajo real, haya marcado o no), pero un
  // fallo al guardarla no puede tragarse el "hecho": la tarea queda marcada igual.
  const cerrarTemporizador = useCallback(
    async (plan: number, real: number, marcar: boolean) => {
      const t = timerTarget;
      setTimerTarget(null);
      if (!t) return;
      try {
        await workSessionApi.create({
          kind: t.kind,
          task_id: t.taskId,
          planned_seconds: plan,
          actual_seconds: real,
          completed_at: null,
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : "No se pudo guardar la sesión");
      }
      if (!marcar) return;
      const f = t.focus;
      if (f.kind === "plan") {
        await togglePlan(f.examId, f.item);
      } else {
        const doneOn = f.task.due_on && !f.task.rec_type ? f.task.due_on : f.task.pending ?? today;
        await toggle(f.task, doneOn);
      }
    },
    [timerTarget, toggle, togglePlan, today],
  );

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
            {carga && <CargaDelDia carga={carga} />}

            {timeline && (
              <TimelineDelDia
                timeline={timeline}
                citas={citasPorId}
                esAdulto={!isChild}
                onNueva={() => setCitaDialog({ cita: null, fecha: today })}
                onEditar={(c) => setCitaDialog({ cita: c, fecha: today })}
                onBorrar={(id) => void borrarCita(id)}
              />
            )}

            {focus && (
          <FocusCard
            focus={focus}
            today={today}
            onToggleTask={toggle}
            onTogglePlan={togglePlan}
            onStart={abrirTemporizador}
            onAjustar={() => void aplicarEstimacion()}
            estimacion={estimacion}
            ajustando={ajustando}
            restToday={groups.hoy.length + examPlanItems.length - 1}
            overdueCount={groups.atrasadas.length}
          />
            )}

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

      <TimerDialog
        target={timerTarget}
        onClose={() => setTimerTarget(null)}
        onFinish={(plan, real, marcar) => void cerrarTemporizador(plan, real, marcar)}
      />

      {citaDialog && (
        <CitaDialog
          estado={citaDialog}
          ninos={ninos}
          onClose={() => setCitaDialog(null)}
          onSave={(cuerpo) => void guardarCita(citaDialog, cuerpo)}
        />
      )}
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

/** "Hoy: 2 h 05 min" sin decimales ni "0 min" cuando no hay nada que decir. */
function minutosLegibles(min: number): string {
  if (min <= 0) return "";
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (!h) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

/**
 * Cuánto ocupa el día, en una línea.
 *
 * Solo se enseña si hay algo que contar: un día vacío no necesita un resumen, y
 * la app que avisa de todo avisa de nada. El aviso que sí importa es el que el
 * backend ya sabe que es cierto: minutos del plan que no han cabido bajo el
 * tope, que antes se calculaban y nadie miraba.
 */
function CargaDelDia({ carga }: { carga: DayLoad }) {
  const partes: string[] = [];
  if (carga.task_minutes > 0) partes.push(`${minutosLegibles(carga.task_minutes)} de tareas`);
  if (carga.study_minutes > 0) partes.push(`${minutosLegibles(carga.study_minutes)} de estudio`);
  if (carga.blocked_minutes > 0) {
    // Los minutos bloqueados son de dos cosas distintas y conviene nombrarlas: un
    // bloque que dice "de extraescolar" cuando incluye el dentista del niño está
    // mintiendo sobre lo que ocupa el día.
    const ocupaciones: string[] = [];
    if (carga.extracurricular_minutes > 0) ocupaciones.push(`${minutosLegibles(carga.extracurricular_minutes)} de extraescolar`);
    if (carga.appointment_minutes > 0) {
      ocupaciones.push(
        `${minutosLegibles(carga.appointment_minutes)} de citas${
          carga.appointments_count > 0 ? ` (${carga.appointments_count})` : ""
        }`,
      );
    }
    partes.push(ocupaciones.join(" y "));
  }

  const noCabe = carga.unplaced_study_minutes > 0;
  if (!partes.length && !noCabe) return null;

  return (
    <Paper elevation={0} sx={{ p: 1.5, borderRadius: 2, bgcolor: "background.paper", border: 1, borderColor: "divider" }}>
      <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
        Tu día
      </Typography>
      {partes.length > 0 && (
        <Typography variant="body2" sx={{ mt: 0.25 }}>
          {partes.join(" · ")}
        </Typography>
      )}
      {carga.daily_max_minutes > 0 && (
        <Typography variant="caption" color="text.secondary" component="div">
          Repartiendo el estudio hasta {minutosLegibles(carga.daily_max_minutes)} al día
        </Typography>
      )}
      {carga.tasks_without_estimate > 0 && (
        <Typography variant="caption" color="text.secondary" component="div">
          {carga.tasks_without_estimate} tarea{carga.tasks_without_estimate === 1 ? "" : "s"} sin
          estimación: cuenta como cero hasta que crones una
        </Typography>
      )}
      {noCabe && (
        <Alert severity="warning" sx={{ mt: 1, borderRadius: 1, py: 0 }}>
          Con el reparto actual, {minutosLegibles(carga.unplaced_study_minutes)} del plan no llegan a
          caber en ningún día. Subir el tope en Perfil o dejar un examen para después.
        </Alert>
      )}
    </Paper>
  );
}

function FocusCard({
  focus,
  today,
  onToggleTask,
  onTogglePlan,
  onStart,
  onAjustar,
  estimacion,
  ajustando,
  restToday,
  overdueCount,
}: {
  focus: Focus;
  today: string;
  onToggleTask: (task: Task, doneOn: string) => Promise<void>;
  onTogglePlan: (examId: number, item: PlanItem) => Promise<void>;
  onStart: (focus: Focus) => void;
  onAjustar: () => void;
  estimacion: WorkSessionEstimate | null;
  ajustando: boolean;
  restToday: number;
  overdueCount: number;
}) {
  const isPlan = focus.kind === "plan";
  const label = isPlan
    ? focus.item.label ?? PHASE_LABEL[focus.item.phase] ?? focus.item.phase
    : CATEGORY_LABEL[focus.task.category] ?? focus.task.category;
  const color = isPlan
    ? PHASE_COLOR[focus.item.phase] ?? "#757575"
    : CATEGORY_COLOR[focus.task.category] ?? "#757575";
  const title = isPlan ? focus.subject : focus.task.title;
  const minutes = isPlan ? focus.item.minutes : focus.task.est_minutes;
  const overdue = focus.kind === "task" && focus.overdue;

  // Solo hay texto cuando el backend ya ha decidido que merece mención.
  const sugerenciaMin = estimacion?.suggested_minutes ?? null;
  const referencia = minutes ?? MIN_POR_DEFECTO;
  const sugerencia = sugerenciaMin
    ? estimacion?.based_on === "task"
      ? `Te suele llevar ${sugerenciaMin} min, no ${referencia}.`
      : `Este tipo de tarea te suele llevar ${sugerenciaMin} min.`
    : null;

  const onDone = () => {
    if (focus.kind === "plan") {
      void onTogglePlan(focus.examId, focus.item);
      return;
    }
    const doneOn =
      focus.task.due_on && !focus.task.rec_type ? focus.task.due_on : focus.task.pending ?? today;
    void onToggleTask(focus.task, doneOn);
  };

  const rest: string[] = [];
  if (restToday > 0) rest.push(`+${restToday} más para hoy`);
  if (overdueCount > 0) rest.push(`${overdueCount} atrasada${overdueCount === 1 ? "" : "s"}`);

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 3,
        border: 1,
        borderColor: "primary.main",
        bgcolor: (t) => alpha(t.palette.primary.main, 0.06),
      }}
    >
      <Typography variant="overline" sx={{ color: "primary.main", fontWeight: 700, lineHeight: 1.2 }}>
        Ahora
      </Typography>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap", mt: 0.5 }}>
        <Chip label={label} size="small" sx={{ bgcolor: color, color: "#fff", height: 20 }} />
        <Typography variant="h6" sx={{ fontWeight: 600, flexGrow: 1 }}>
          {title}
        </Typography>
      </Box>
      {minutes ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          ~{minutes} min
        </Typography>
      ) : null}
      {sugerencia ? (
        <Box sx={{ mt: 0.75 }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
            {sugerencia}
          </Typography>
          {focus.kind === "task" ? (
            <Button size="small" onClick={onAjustar} disabled={ajustando} sx={{ mt: 0.25, px: 0.5 }}>
              Ajustar a {estimacion?.suggested_minutes} min
            </Button>
          ) : null}
        </Box>
      ) : null}
      <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
        <Button
          variant="contained"
          fullWidth
          startIcon={<PlayArrowIcon />}
          onClick={() => onStart(focus)}
          sx={{ borderRadius: 2 }}
        >
          Empezar
        </Button>
        <Button variant="outlined" onClick={onDone} sx={{ borderRadius: 2, flexShrink: 0 }}>
          {overdue ? "Ya está hecho" : "Hecho"}
        </Button>
      </Stack>
      {rest.length > 0 && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", mt: 1, textAlign: "center" }}
        >
          {rest.join(" · ")}
        </Typography>
      )}
    </Paper>
  );
}

function TimerDialog({
  target,
  onClose,
  onFinish,
}: {
  target: TimerTarget | null;
  onClose: () => void;
  onFinish: (plan: number, real: number, marcar: boolean) => void;
}) {
  const [plan, setPlan] = useState(0);
  const [restante, setRestante] = useState(0);
  const [corriendo, setCorriendo] = useState(false);
  const [agotado, setAgotado] = useState(false);
  const [guardando, setGuardando] = useState(false);

  // Cada objetivo nuevo reinicia la cuenta; si la tarea no dice cuánto cuesta,
  // se cae al pomodoro de 25 min para no arrancar con un reloj en cero.
  useEffect(() => {
    if (!target) return;
    const seg = (target.minutos > 0 ? target.minutos : MIN_POR_DEFECTO) * 60;
    setPlan(seg);
    setRestante(seg);
    setAgotado(false);
    setCorriendo(true);
    setGuardando(false);
  }, [target]);

  useEffect(() => {
    if (!corriendo) return;
    const id = setInterval(() => setRestante((r) => Math.max(0, r - 1)), 1000);
    return () => clearInterval(id);
  }, [corriendo]);

  useEffect(() => {
    if (restante === 0 && corriendo) {
      setCorriendo(false);
      setAgotado(true);
    }
  }, [restante, corriendo]);

  const ampliar = () => {
    setPlan((p) => p + 300);
    setRestante((r) => r + 300);
    setAgotado(false);
    setCorriendo(true);
  };

  const progreso = plan > 0 ? ((plan - restante) / plan) * 100 : 0;
  const porDefecto = !target || target.minutos <= 0;

  return (
    <Dialog open={!!target} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Typography sx={{ flexGrow: 1, fontWeight: 600 }}>{target?.title ?? ""}</Typography>
        <IconButton onClick={onClose} size="small" aria-label="Cerrar sin guardar">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
          {agotado ? (
            <Typography variant="h3" sx={{ fontWeight: 700 }}>
              ¡Tiempo!
            </Typography>
          ) : (
            <Box sx={{ position: "relative", display: "inline-flex" }}>
              <CircularProgress variant="determinate" value={progreso} size={148} thickness={4} />
              <Box
                sx={{
                  top: 0,
                  left: 0,
                  right: 0,
                  bottom: 0,
                  position: "absolute",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Typography variant="h4" sx={{ fontWeight: 700 }}>
                  {mmss(restante)}
                </Typography>
              </Box>
            </Box>
          )}
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: "center" }}>
          {agotado
            ? "¿Lo has terminado?"
            : `Plan: ~${Math.round(plan / 60)} min${porDefecto ? " (por defecto)" : ""}`}
        </Typography>
      </DialogContent>
      <DialogActions sx={{ flexDirection: "column", gap: 1, alignItems: "stretch" }}>
        {agotado ? (
          <>
            <Button
              variant="contained"
              disabled={guardando}
              onClick={() => {
                setGuardando(true);
                onFinish(plan, plan, true);
              }}
              sx={{ borderRadius: 2 }}
            >
              Marcar como hecho
            </Button>
            <Button variant="outlined" disabled={guardando} onClick={ampliar} sx={{ borderRadius: 2 }}>
              Seguir 5 min más
            </Button>
          </>
        ) : (
          <>
            <Stack direction="row" spacing={1}>
              <Button
                variant="outlined"
                fullWidth
                onClick={() => setCorriendo((c) => !c)}
                sx={{ borderRadius: 2 }}
              >
                {corriendo ? "Pausar" : "Seguir"}
              </Button>
              <Button variant="outlined" onClick={ampliar} sx={{ borderRadius: 2, flexShrink: 0 }}>
                +5 min
              </Button>
            </Stack>
            <Button
              variant="contained"
              disabled={guardando}
              onClick={() => {
                setGuardando(true);
                onFinish(plan, plan - restante, true);
              }}
              sx={{ borderRadius: 2 }}
            >
              Terminar y marcar
            </Button>
          </>
        )}
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
/** Estado del diálogo de citas: `cita` a null es una cita nueva. */
interface CitaDialogState {
  cita: Appointment | null;
  fecha: string;
}

/** Una fila de la línea: o un hueco o un bloque que lo ocupa. */
type Linea =
  | { tipo: "hueco"; key: string; inicio: string; fin: string; minutos: number }
  | { tipo: "bloque"; key: string; bloque: DayBlock };

const BLOCK_LABEL: Record<string, string> = {
  cita: "Cita",
  extraescolar: "Extraescolar",
  extraescolar_compartida: "Llevar a",
  comida: "Comida",
};

const BLOCK_COLOR: Record<string, string> = {
  cita: "#c62828",
  extraescolar: "#6a1b9a",
  extraescolar_compartida: "#ef6c00",
  comida: "#558b2f",
};

/**
 * La segunda línea de un bloque. En las comidas manda la franja y no el tipo:
 * "Merienda" y "Desayuno" se distinguen por la hora, pero el nombre de la franja es
 * lo que el usuario activó y lo que espera leer.
 */
function etiquetaDe(b: DayBlock): string {
  if (b.kind === "comida" && b.slot) return b.slot.charAt(0).toUpperCase() + b.slot.slice(1);
  return BLOCK_LABEL[b.kind] ?? b.kind;
}

/** "09:00:00" -> "09:00". El backend siempre devuelve segundos. */
function hhmm(hora: string): string {
  return hora.slice(0, 5);
}

/**
 * La línea del día: lo que está ocupado, en orden, y el hueco que queda.
 *
 * Los bloques no se solapan nunca en la respuesta, pero dos hermanos en la misma
 * actividad sí se muestran por separado: son dos viajes que nombrar, aunque para
 * el cálculo de minutos se unan en uno.
 */
function TimelineDelDia({
  timeline,
  citas,
  esAdulto,
  onNueva,
  onEditar,
  onBorrar,
}: {
  timeline: DayTimeline;
  /** Las citas completas de hoy, por id. El bloque solo trae el id. */
  citas: Map<number, Appointment>;
  esAdulto: boolean;
  onNueva: () => void;
  onEditar: (c: Appointment) => void;
  onBorrar: (id: number) => void;
}) {
  // Una sola lista mezclando huecos y bloques, en orden de hora. Separarlos en
  // "ocupaciones" y "citas" era más fácil de montar, pero obligaba a leer dos
  // listas para saber si a las seis de la tarde había algo libre: el hueco es
  // justo lo que se pierde al ordenar por tipo.
  const lineas = useMemo(() => {
    const items: Linea[] = [
      ...(timeline.huecos ?? []).map((h, i) => ({
        tipo: "hueco" as const,
        key: `hueco-${i}-${h.start}`,
        inicio: h.start,
        fin: h.end,
        minutos: h.minutes,
      })),
      ...timeline.blocks.map((b) => ({
        tipo: "bloque" as const,
        key: `bloque-${b.kind}-${b.cita_id ?? b.extra_id ?? b.slot ?? b.title}-${b.start}`,
        bloque: b,
      })),
    ];
    const hora = (l: Linea) => (l.tipo === "hueco" ? l.inicio : l.bloque.start);
    // Las "HH:MM:SS" se comparan como texto y ordenan bien: mismo formato, mismo
    // ancho, y los huecos empiezan siempre en punto.
    items.sort((a, b) => (hora(a) < hora(b) ? -1 : hora(a) > hora(b) ? 1 : 0));
    return items;
  }, [timeline]);

  return (
    <section>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          Tu línea del día
        </Typography>
        {esAdulto && (
          <Button size="small" variant="outlined" onClick={onNueva}>
            + Cita
          </Button>
        )}
      </Stack>

      {lineas.length === 0 ? (
        <Alert severity="success" sx={{ borderRadius: 2 }}>
          Nada ocupa el día.
        </Alert>
      ) : (
        <List sx={{ p: 0 }}>
          {lineas.map((l) =>
            l.tipo === "hueco" ? (
              <HuecoRow key={l.key} inicio={l.inicio} fin={l.fin} minutos={l.minutos} />
            ) : (
              <DayBlockRow
                key={l.key}
                block={l.bloque}
                esSemanal={l.bloque.cita_id !== null && citas.get(l.bloque.cita_id)?.repeats_weekly === true}
                onEditar={
                  esAdulto && l.bloque.cita_id !== null && citas.has(l.bloque.cita_id)
                    ? () => onEditar(citas.get(l.bloque.cita_id as number) as Appointment)
                    : undefined
                }
                onBorrar={esAdulto && l.bloque.cita_id ? () => onBorrar(l.bloque.cita_id as number) : undefined}
              />
            ),
          )}
        </List>
      )}
    </section>
  );
}

/** Una franja sin nada encima: el rato donde sí se puede colocar algo. */
function HuecoRow({ inicio, fin, minutos }: { inicio: string; fin: string; minutos: number }) {
  return (
    <ListItem disableGutters>
      <Box sx={{ display: "flex", gap: 1, alignItems: "baseline", width: "100%" }}>
        <Box sx={{ width: 4, alignSelf: "stretch", bgcolor: "#c5e1a5", borderRadius: 2, minHeight: 34 }} />
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }} noWrap>
            {hhmm(inicio)}–{hhmm(fin)} · Libre
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap>
            Hueco para colocar algo
          </Typography>
        </Box>
        <Typography variant="caption" color="text.secondary">
          {minutosLegibles(minutos)}
        </Typography>
      </Box>
    </ListItem>
  );
}

function DayBlockRow({
  block,
  esSemanal,
  onEditar,
  onBorrar,
}: {
  block: DayBlock;
  esSemanal?: boolean;
  onEditar?: () => void;
  onBorrar?: () => void;
}) {
  const color = BLOCK_COLOR[block.kind] ?? "#616161";
  const etiqueta = block.affected.length > 0 ? ` · ${block.affected.join(", ")}` : "";
  return (
    <ListItem
      disableGutters
      secondaryAction={
        onEditar || onBorrar ? (
          <ListItemSecondaryAction>
            {onEditar && (
              <Button size="small" onClick={onEditar} aria-label={`Editar ${block.title}`}>
                Editar
              </Button>
            )}
            {onBorrar && (
              <Button size="small" color="error" onClick={onBorrar} aria-label={`Borrar ${block.title}`}>
                Borrar
              </Button>
            )}
          </ListItemSecondaryAction>
        ) : undefined
      }
    >
      <Box sx={{ display: "flex", gap: 1, alignItems: "baseline", width: "100%", pr: onEditar || onBorrar ? 14 : 0 }}>
        <Box
          sx={{
            width: 4,
            alignSelf: "stretch",
            bgcolor: color,
            borderRadius: 2,
            minHeight: 34,
          }}
        />
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }} noWrap>
            {hhmm(block.start)}–{hhmm(block.end)} · {block.title}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap>
            {etiquetaDe(block)}
            {esSemanal ? " · cada semana" : ""}
            {etiqueta}
            {block.place ? ` · ${block.place}` : ""}
          </Typography>
        </Box>
        <Typography variant="caption" color="text.secondary">
          {minutosLegibles(block.minutes)}
        </Typography>
      </Box>
    </ListItem>
  );
}

/**
 * Alta y edición de citas.
 *
 * El adulto que guarda es siempre afectado y por eso no aparece en la lista: solo se
 * elige a quién más le afecta. Si no se marca a nadie, la cita es solo suya.
 */
function CitaDialog({
  estado,
  ninos,
  onClose,
  onSave,
}: {
  estado: CitaDialogState;
  ninos: User[];
  onClose: () => void;
  onSave: (cuerpo: AppointmentInput) => void;
}) {
  const editando = estado.cita !== null;
  const [titulo, setTitulo] = useState(estado.cita?.title ?? "");
  const [lugar, setLugar] = useState(estado.cita?.place ?? "");
  const [fecha, setFecha] = useState(estado.cita?.date ?? estado.fecha);
  const [desde, setDesde] = useState(hhmm(estado.cita?.start_time ?? "17:00"));
  const [hasta, setHasta] = useState(hhmm(estado.cita?.end_time ?? "18:00"));
  const [repite, setRepite] = useState(estado.cita?.repeats_weekly ?? false);
  const [hastaFecha, setHastaFecha] = useState(estado.cita?.until ?? "");
  const [afectados, setAfectados] = useState<number[]>(
    estado.cita?.affected.map((p) => p.id).filter((id) => id > 0) ?? [],
  );

  const alternar = (id: number) =>
    setAfectados((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const guardar = () => {
    onSave({
      title: titulo.trim(),
      place: lugar.trim() ? lugar.trim() : null,
      date: fecha,
      start_time: desde,
      end_time: hasta,
      repeats_weekly: repite,
      until: repite && hastaFecha ? hastaFecha : null,
      affected_user_ids: afectados,
    });
  };

  const invalido = titulo.trim() === "" || desde >= hasta;

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{editando ? "Editar cita" : "Nueva cita"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          <TextField
            label="Qué es"
            value={titulo}
            onChange={(e) => setTitulo(e.target.value)}
            autoFocus
            fullWidth
          />
          <TextField label="Dónde" value={lugar} onChange={(e) => setLugar(e.target.value)} fullWidth />

          <TextField
            label="Día"
            type="date"
            value={fecha}
            onChange={(e) => setFecha(e.target.value)}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />

          <Stack direction="row" spacing={2}>
            <TextField
              label="Desde"
              type="time"
              value={desde}
              onChange={(e) => setDesde(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <TextField
              label="Hasta"
              type="time"
              value={hasta}
              onChange={(e) => setHasta(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
          </Stack>

          <FormControlLabel
            control={<Checkbox checked={repite} onChange={(e) => setRepite(e.target.checked)} />}
            label="Cada semana"
          />
          {repite && (
            <TextField
              label="Hasta qué día (opcional)"
              type="date"
              value={hastaFecha}
              onChange={(e) => setHastaFecha(e.target.value)}
              InputLabelProps={{ shrink: true }}
              fullWidth
              helperText="Si lo dejas vacío, no tiene final."
            />
          )}

          {ninos.length > 0 && (
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                A quién más le afecta
              </Typography>
              {ninos.map((n) => (
                <FormControlLabel
                  key={n.id}
                  control={
                    <Checkbox
                      checked={afectados.includes(n.id)}
                      onChange={() => alternar(n.id)}
                      inputProps={{ "aria-label": n.display_name ?? `Niño ${n.id}` }}
                    />
                  }
                  label={n.display_name ?? `Niño ${n.id}`}
                />
              ))}
              <Typography variant="caption" color="text.secondary">
                Si no marcas a nadie, la cita es solo tuya.
              </Typography>
            </Box>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="contained" onClick={guardar} disabled={invalido}>
          Guardar
        </Button>
      </DialogActions>
    </Dialog>
  );
}

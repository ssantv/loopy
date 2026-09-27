import { useCallback, useEffect, useMemo, useState } from "react";
import { BOTTOM_BAR_PADDING, PageNav } from "../components/Nav";
import { calendarApi, examApi, subjectApi, taskApi, type Calendar, type CalendarDay, type CalendarTask, type PlanPhase } from "../api/client";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import type { SxProps } from "@mui/material/styles";

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

const WEEKDAY_LABEL = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];

const CATEGORY_COLOR: Record<string, string> = {
  general: "#757575",
  hogar: "#8d6e63",
  "colegio-deberes": "#0288d1",
  "colegio-trabajo": "#7b1fa2",
  puntual: "#ef6c00",
};

function parseISO(d: string): Date {
  return new Date(d + "T00:00:00");
}

function toISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function addDays(d: Date, n: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
}

function todayISO(): string {
  return toISO(new Date());
}

function weekStart(d: Date): Date {
  const out = new Date(d);
  const dow = (out.getDay() + 6) % 7; // 0=lunes
  out.setDate(out.getDate() - dow);
  return out;
}

function monthRange(d: Date): { from: string; to: string; firstDay: Date; daysInMonth: number } {
  const first = new Date(d.getFullYear(), d.getMonth(), 1);
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
  return {
    from: toISO(first),
    to: toISO(last),
    firstDay: first,
    daysInMonth: last.getDate(),
  };
}

function fmtTitle(d: Date): string {
  return d.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
}

function fmtShort(d: Date): string {
  return d.toLocaleDateString("es-ES", { day: "numeric", month: "short" });
}

export default function Calendario() {
  const [mode, setMode] = useState<"semana" | "mes">("semana");
  const [anchor, setAnchor] = useState<Date>(new Date());
  const [data, setData] = useState<Calendar | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sessionDate, setSessionDate] = useState<string | null>(null);
  const [openDay, setOpenDay] = useState<string | null>(null);
  const [subjects, setSubjects] = useState<{ id: number; name: string }[]>([]);

  // Poblar subjects solo si hay exámenes (diálogo adelantar)
  const planSubjects = useMemo(() => {
    const seen = new Map<number, string>();
    for (const day of Object.values(data?.days ?? {})) {
      for (const p of day.plan) {
        if (p.subject_id != null && !seen.has(p.subject_id)) seen.set(p.subject_id, p.subject_name ?? "");
      }
    }
    return [...seen.entries()].map(([id, name]) => ({ id, name }));
  }, [data]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let from: string;
      let to: string;
      if (mode === "semana") {
        const start = weekStart(anchor);
        from = toISO(start);
        to = toISO(addDays(start, 6));
      } else {
        const r = monthRange(anchor);
        from = r.from;
        to = r.to;
      }
      const cal = await calendarApi.get(from, to);
      // Normalizar claves: asegurar todas las fechas del rango presentes
      const days: Record<string, CalendarDay> = {};
      const start = parseISO(from);
      const end = parseISO(to);
      for (let d = new Date(start); d <= end; d = addDays(d, 1)) {
        days[toISO(d)] = cal.days[toISO(d)] ?? { tasks: [], plan: [] };
      }
      setData({ from, to, days });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar el calendario");
    } finally {
      setLoading(false);
    }
  }, [mode, anchor]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (data && Object.keys(data.days).length > 0) {
      const ids = new Set<number>();
      for (const day of Object.values(data.days)) for (const t of day.tasks) if (t.subject_id) ids.add(t.subject_id);
      if (ids.size > 0) {
        void subjectApi.list().then((rows) => setSubjects(rows));
      }
    }
  }, [data]);

  const nav = useCallback((dir: -1 | 1) => {
    setAnchor((prev) => {
      if (mode === "semana") return addDays(prev, 7 * dir);
      return new Date(prev.getFullYear(), prev.getMonth() + dir, 1);
    });
  }, [mode]);

  const toggleTask = useCallback(
    async (task: CalendarTask, dateISO: string, done: boolean) => {
      try {
        if (done) await taskApi.undo(task.id, dateISO);
        else await taskApi.complete(task.id, dateISO);
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al actualizar la tarea");
      }
    },
    [load],
  );

  const togglePlan = useCallback(
    async (examId: number, dateISO: string, status: "done" | "skip" | null) => {
      try {
        if (status === "done") await examApi.undoPlanItem(examId, dateISO);
        else await examApi.markPlanItem(examId, dateISO, "done");
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al actualizar el estudio");
      }
    },
    [load],
  );

  const addSessionCallback = useCallback(
    async (subjectId: number, phase: PlanPhase) => {
      if (!sessionDate) return;
      try {
        await subjectApi.addSession(subjectId, { date: sessionDate, phase });
        setSessionDate(null);
        void load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al registrar la sesión");
      }
    },
    [sessionDate, load],
  );

  const title =
    mode === "semana"
      ? `${fmtShort(weekStart(anchor))} – ${fmtShort(addDays(weekStart(anchor), 6))}`
      : anchor.toLocaleDateString("es-ES", { month: "long", year: "numeric" });

  return (
    <Box>
      <PageNav title="Calendario" />

      <Box sx={{ maxWidth: 860, margin: "0 auto", padding: "1.5rem 1rem", pb: BOTTOM_BAR_PADDING }}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }} flexWrap="wrap">
          <Button variant="outlined" size="small" onClick={() => nav(-1)}>
            ◀
          </Button>
          <Button variant="outlined" size="small" onClick={() => nav(1)}>
            ▶
          </Button>
          <Button size="small" onClick={() => setAnchor(new Date())}>
            Hoy
          </Button>
          <Typography variant="subtitle1" sx={{ textTransform: "capitalize", flexGrow: 1 }}>
            {title}
          </Typography>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={mode}
            onChange={(_e, v) => v && setMode(v as "semana" | "mes")}
          >
            <ToggleButton value="semana">Semana</ToggleButton>
            <ToggleButton value="mes">Mes</ToggleButton>
          </ToggleButtonGroup>
        </Stack>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {loading ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
            <CircularProgress />
          </Box>
        ) : data ? (
          mode === "mes" ? (
            <MonthGrid
              days={data.days}
              firstDay={monthRange(anchor).firstDay}
              daysInMonth={monthRange(anchor).daysInMonth}
              today={todayISO()}
              onOpenDay={setOpenDay}
              onAddSession={setSessionDate}
            />
          ) : (
            <WeekList
              days={data.days}
              today={todayISO()}
              onToggleTask={toggleTask}
              onTogglePlan={togglePlan}
              onAddSession={setSessionDate}
            />
          )
        ) : null}
      </Box>

      <SessionDialog
        open={sessionDate !== null}
        date={sessionDate}
        subjects={planSubjects.length > 0 ? planSubjects : subjects}
        onClose={() => setSessionDate(null)}
        onAdd={(sid, phase) => void addSessionCallback(sid, phase)}
      />

      <DayDialog
        date={openDay}
        day={openDay ? (data?.days[openDay] ?? { tasks: [], plan: [] }) : null}
        onClose={() => setOpenDay(null)}
        onToggleTask={toggleTask}
        onTogglePlan={togglePlan}
        onAddSession={(iso) => {
          setOpenDay(null);
          setSessionDate(iso);
        }}
      />
    </Box>
  );
}

/** Detalle de un dia concreto, al tocarlo en la vista de mes. */
function DayDialog({
  date,
  day,
  onClose,
  onToggleTask,
  onTogglePlan,
  onAddSession,
}: {
  date: string | null;
  day: CalendarDay | null;
  onClose: () => void;
  onToggleTask: (t: CalendarTask, dateISO: string, done: boolean) => Promise<void>;
  onTogglePlan: (examId: number, dateISO: string, status: "done" | "skip" | null) => Promise<void>;
  onAddSession: (dateISO: string) => void;
}) {
  return (
    <Dialog open={date !== null} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle sx={{ textTransform: "capitalize" }}>
        {date ? fmtTitle(parseISO(date)) : ""}
      </DialogTitle>
      <DialogContent>
        {day ? (
          <DayCell
            dayISO={date as string}
            day={day}
            today=""
            onToggleTask={onToggleTask}
            onTogglePlan={onTogglePlan}
            onAddSession={onAddSession}
          />
        ) : null}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cerrar</Button>
      </DialogActions>
    </Dialog>
  );
}

function DayCell({
  dayISO,
  day,
  today,
  onToggleTask,
  onTogglePlan,
  onAddSession,
}: {
  dayISO: string;
  day: CalendarDay;
  today: string;
  onToggleTask: (t: CalendarTask, dateISO: string, done: boolean) => Promise<void>;
  onTogglePlan: (examId: number, dateISO: string, status: "done" | "skip" | null) => Promise<void>;
  onAddSession: (dateISO: string) => void;
}) {
  const date = parseISO(dayISO);
  const isToday = dayISO === today;
  // Sin altura fija ni scroll: la celda crece con su contenido y el scroll
  // lo lleva la pagina, no una caja dentro de otra.
  const cellSx: SxProps = {
    border: 1,
    borderColor: isToday ? "primary.main" : "divider",
    borderRadius: 1,
    p: 0.5,
    bgcolor: isToday ? "primary.light" : "background.paper",
    display: "flex",
    flexDirection: "column",
    gap: 0.25,
  };
  const header = (
    <Stack direction="row" spacing={0.5} alignItems="center">
      <Typography variant="caption" sx={{ fontWeight: isToday ? 700 : 400 }}>
        {`${WEEKDAY_LABEL[(date.getDay() + 6) % 7]} ${date.getDate()}`}
      </Typography>
      <Button size="small" sx={{ ml: "auto", minWidth: 0, p: 0 }} onClick={() => onAddSession(dayISO)}>
        +
      </Button>
    </Stack>
  );
  return (
    <Box data-dia={dayISO} sx={cellSx}>
      {header}
      {day.plan.map((p, i) => (
        <Chip
          key={`plan-${i}`}
          label={`${p.subject_name ?? ""} · ${p.label ?? PHASE_LABEL[p.phase] ?? p.phase}`}
          size="small"
          clickable
          onClick={() => void onTogglePlan(p.exam_id ?? 0, dayISO, p.status)}
          icon={
            <Checkbox
              size="small"
              checked={p.status === "done"}
              indeterminate={p.status === "skip"}
              sx={{ color: "#fff", "& .MuiSvgIcon-root": { fontSize: 16 } }}
            />
          }
          sx={{
            bgcolor: p.status === "done" ? "#9e9e9e" : PHASE_COLOR[p.phase] ?? "#757575",
            color: "#fff",
            height: "auto",
            minHeight: 24,
            justifyContent: "flex-start",
            display: "flex",
            width: "100%",
          }}
        />
      ))}
      {day.tasks.map((t) => (
        <Stack key={t.id} direction="row" spacing={0.5} alignItems="center" onClick={() => void onToggleTask(t, dayISO, t.done)} sx={{ cursor: "pointer" }}>
          <Checkbox size="small" checked={t.done} tabIndex={-1} disableRipple readOnly sx={{ p: 0.25 }} />
          <Typography
            variant="caption"
            sx={{ textDecoration: t.done ? "line-through" : "none", opacity: t.done ? 0.6 : 1 }}
          >
            {t.title}
          </Typography>
        </Stack>
      ))}
      {day.plan.length === 0 && day.tasks.length === 0 && (
        <Typography variant="caption" color="text.disabled">
          —
        </Typography>
      )}
    </Box>
  );
}

/** Cuantos indicadores caben en una celda de mes sin que se partan en dos lineas. */
const MAX_DOTS = 4;

/**
 * Celda del mes: altura fija y sin scroll. Solo el numero del dia y un punto
 * de color por cada cosa pendiente, asi el mes se lee de un vistazo. El
 * detalle vive en el dialogo al tocar el dia.
 */
function MonthCell({
  dayISO,
  day,
  today,
  onOpenDay,
  onAddSession,
}: {
  dayISO: string;
  day: CalendarDay;
  today: string;
  onOpenDay: (dateISO: string) => void;
  onAddSession: (dateISO: string) => void;
}) {
  const isToday = dayISO === today;
  const items = [
    ...day.plan.map((p) => ({ color: p.status === "done" ? "#bdbdbd" : (PHASE_COLOR[p.phase] ?? "#757575"), done: p.status === "done" })),
    ...day.tasks.map((t) => ({ color: CATEGORY_COLOR[t.category] ?? "#757575", done: t.done })),
  ];
  const shown = items.slice(0, MAX_DOTS);
  const rest = items.length - shown.length;

  return (
    <Box
      data-date={dayISO}
      onClick={() => onOpenDay(dayISO)}
      sx={{
        height: 62,
        border: 1,
        borderColor: isToday ? "primary.main" : "divider",
        borderRadius: 1,
        p: 0.5,
        bgcolor: isToday ? "primary.light" : "background.paper",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        cursor: "pointer",
        "&:hover": { borderColor: "primary.main" },
      }}
    >
      <Stack direction="row" alignItems="center" sx={{ minHeight: 18 }}>
        <Typography variant="caption" sx={{ fontWeight: isToday ? 700 : 400, lineHeight: 1.2 }}>
          {parseISO(dayISO).getDate()}
        </Typography>
        <Button
          size="small"
          aria-label="Registrar sesión"
          sx={{ ml: "auto", minWidth: 0, p: 0, lineHeight: 1 }}
          onClick={(e) => {
            e.stopPropagation();
            onAddSession(dayISO);
          }}
        >
          +
        </Button>
      </Stack>

      {shown.length > 0 && (
        <Stack direction="row" spacing={0.25} sx={{ mt: 0.25, flexWrap: "wrap" }}>
          {shown.map((it, i) => (
            <Box
              key={i}
              sx={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                bgcolor: it.color,
                opacity: it.done ? 0.45 : 1,
              }}
            />
          ))}
          {rest > 0 && (
            <Typography variant="caption" sx={{ fontSize: 9, lineHeight: 1, color: "text.secondary" }}>
              +{rest}
            </Typography>
          )}
        </Stack>
      )}
    </Box>
  );
}

function MonthGrid({
  days,
  firstDay,
  daysInMonth,
  today,
  onOpenDay,
  onAddSession,
}: {
  days: Record<string, CalendarDay>;
  firstDay: Date;
  daysInMonth: number;
  today: string;
  onOpenDay: (dateISO: string) => void;
  onAddSession: (dateISO: string) => void;
}) {
  const first = firstDay;
  const leading = (first.getDay() + 6) % 7;
  const cells: (string | null)[] = Array.from({ length: leading }, () => null);
  for (let i = 1; i <= daysInMonth; i++) {
    cells.push(toISO(new Date(first.getFullYear(), first.getMonth(), i)));
  }
  // Rejilla de 7 columnas iguales en vez de filas con flex: los huecos de la
  // primera y de la ultima semana siguen ocupando su columna, asi que el dia
  // 28/29/30 sigue cayendo en lunes/martes/miercoles y no se ensancha.
  const columnas = { display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 1 } as const;
  return (
    <Stack spacing={0.5}>
      <Box sx={columnas}>
        {WEEKDAY_LABEL.map((w) => (
          <Typography key={w} variant="caption" color="text.secondary" sx={{ textAlign: "center" }}>
            {w}
          </Typography>
        ))}
      </Box>
      <Box sx={columnas}>
        {cells.map((iso, i) =>
          iso ? (
            <MonthCell
              key={iso}
              dayISO={iso}
              day={days[iso] ?? { tasks: [], plan: [] }}
              today={today}
              onOpenDay={onOpenDay}
              onAddSession={onAddSession}
            />
          ) : (
            <Box key={`vacio-${i}`} sx={{ height: 62 }} />
          ),
        )}
      </Box>
    </Stack>
  );
}

function WeekList({
  days,
  today,
  onToggleTask,
  onTogglePlan,
  onAddSession,
}: {
  days: Record<string, CalendarDay>;
  today: string;
  onToggleTask: (t: CalendarTask, dateISO: string, done: boolean) => Promise<void>;
  onTogglePlan: (examId: number, dateISO: string, status: "done" | "skip" | null) => Promise<void>;
  onAddSession: (dateISO: string) => void;
}) {
  return (
    <Stack spacing={1}>
      {Object.entries(days).map(([iso, day]) => (
        <DayCell
          key={iso}
          dayISO={iso}
          day={day}
          today={today}
          onToggleTask={onToggleTask}
          onTogglePlan={onTogglePlan}
          onAddSession={onAddSession}
        />
      ))}
    </Stack>
  );
}

function SessionDialog({
  open,
  date,
  subjects,
  onClose,
  onAdd,
}: {
  open: boolean;
  date: string | null;
  subjects: { id: number; name: string }[];
  onClose: () => void;
  onAdd: (subjectId: number, phase: PlanPhase) => void;
}) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{date ? `Adelantar sesión el ${fmtTitle(parseISO(date))}` : "Adelantar sesión"}</DialogTitle>
      <DialogContent>
        {subjects.length === 0 ? (
          <Typography color="text.secondary">No hay asignaturas para adelantar.</Typography>
        ) : (
          <Stack spacing={1.5}>
            <Typography variant="body2" color="text.secondary">
              Registra una sesión hecha por tu cuenta en esta fecha.
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
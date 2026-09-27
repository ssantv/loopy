import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { BOTTOM_BAR_PADDING, PageNav, SubNav } from "../components/Nav";
import { examApi, subjectApi, type Exam, type ExamPlan, type PlanItem, type Subject } from "../api/client";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Divider from "@mui/material/Divider";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import LinearProgress from "@mui/material/LinearProgress";
import Chip from "@mui/material/Chip";

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
  return date.toLocaleDateString("es-ES", { day: "numeric", month: "long" });
}

function todayISO(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function phaseChip(phase: string) {
  return (
    <Chip
      label={PHASE_LABEL[phase] ?? phase}
      size="small"
      component="span"
      sx={{ bgcolor: PHASE_COLOR[phase] ?? "#757575", color: "#fff", height: 20 }}
    />
  );
}

interface PhaseValues {
  days_resumen: number;
  days_estudio: number;
  days_practica: number;
  days_repaso: number;
  include_weekends: boolean;
  resumen_total_pages: number | null;
}

const DEFAULT_PHASES: PhaseValues = {
  days_resumen: 1,
  days_estudio: 1,
  days_practica: 1,
  days_repaso: 1,
  include_weekends: true,
  resumen_total_pages: null,
};

function phaseValuesOf(subject: Subject): PhaseValues {
  return {
    days_resumen: subject.days_resumen,
    days_estudio: subject.days_estudio,
    days_practica: subject.days_practica,
    days_repaso: subject.days_repaso,
    include_weekends: subject.include_weekends,
    resumen_total_pages: subject.resumen_total_pages,
  };
}

function PhaseFields({
  value,
  onChange,
}: {
  value: PhaseValues;
  onChange: (patch: Partial<PhaseValues>) => void;
}) {
  const numField = (
    label: string,
    key: "days_resumen" | "days_estudio" | "days_practica" | "days_repaso",
  ) => (
    <TextField
      size="small"
      type="number"
      inputProps={{ min: 0 }}
      label={label}
      value={value[key]}
      onChange={(ev) => onChange({ [key]: Math.max(0, Number(ev.target.value) || 0) })}
      sx={{ width: 92 }}
    />
  );
  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", alignItems: "center" }}>
        {numField("Resumen", "days_resumen")}
        {numField("Estudio", "days_estudio")}
        {numField("Práctica", "days_practica")}
        {numField("Repaso", "days_repaso")}
        <FormControlLabel
          control={
            <Checkbox
              checked={value.include_weekends}
              onChange={(ev) => onChange({ include_weekends: ev.target.checked })}
            />
          }
          label="Fines de semana"
        />
      </Stack>
      <Stack direction="row" spacing={1} sx={{ mt: 1, alignItems: "center" }}>
        <TextField
          size="small"
          type="number"
          inputProps={{ min: 1 }}
          label="Hojas del tema (opcional)"
          value={value.resumen_total_pages ?? ""}
          onChange={(ev) => {
            const raw = ev.target.value;
            onChange({ resumen_total_pages: raw === "" ? null : Math.max(1, Number(raw) || 1) });
          }}
          sx={{ width: 200 }}
        />
        <Typography variant="caption" color="text.secondary">
          Días antes del examen por fase; Práctica a 0 si la asignatura no la necesita.
        </Typography>
      </Stack>
    </Box>
  );
}

export default function Colegio() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [exams, setExams] = useState<Exam[]>([]);
  const [plans, setPlans] = useState<Record<number, ExamPlan>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const today = useMemo(todayISO, []);

  const [newSubjectName, setNewSubjectName] = useState("");
  const [newPhases, setNewPhases] = useState<PhaseValues>(DEFAULT_PHASES);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editPhases, setEditPhases] = useState<PhaseValues | null>(null);
  const [newExamSubject, setNewExamSubject] = useState<number>(0);
  const [newExamDate, setNewExamDate] = useState<string>(() => todayISO());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [subs, exs] = await Promise.all([subjectApi.list(), examApi.list()]);
      setSubjects(subs);
      setExams(exs);
      setNewExamSubject((cur) => (cur === 0 && subs.length > 0 ? subs[0].id : cur));
      const next = exs.filter((e) => e.exam_date >= today).slice(0, 5);
      const planMap: Record<number, ExamPlan> = {};
      for (const e of next) {
        planMap[e.id] = await examApi.plan(e.id, today);
      }
      setPlans(planMap);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar el colegio");
    } finally {
      setLoading(false);
    }
  }, [today]);

  useEffect(() => {
    void load();
  }, [load]);

  const addSubject = useCallback(async () => {
    const name = newSubjectName.trim();
    if (!name) return;
    try {
      await subjectApi.create({ name, color: null, ...newPhases });
      setNewSubjectName("");
      setNewPhases(DEFAULT_PHASES);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al crear asignatura");
    }
  }, [newSubjectName, newPhases, load]);

  const startEdit = useCallback((subject: Subject) => {
    setEditingId(subject.id);
    setEditPhases(phaseValuesOf(subject));
  }, []);

  const saveEdit = useCallback(async () => {
    if (editingId === null || editPhases === null) return;
    try {
      await subjectApi.update(editingId, editPhases);
      setEditingId(null);
      setEditPhases(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar la asignatura");
    }
  }, [editingId, editPhases, load]);

  const addExam = useCallback(async () => {
    if (!newExamSubject || !newExamDate) return;
    try {
      await examApi.create({ subject_id: newExamSubject, exam_date: newExamDate });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al crear examen");
    }
  }, [newExamSubject, newExamDate, load]);

  const togglePlanItem = useCallback(
    async (examId: number, item: PlanItem) => {
      try {
        if (item.status) {
          await examApi.undoPlanItem(examId, item.date);
        } else {
          await examApi.markPlanItem(examId, item.date, "done");
        }
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al actualizar el plan");
      }
    },
    [load],
  );

  const advanceResumen = useCallback(
    async (subjectId: number) => {
      try {
        await subjectApi.advanceResumen(subjectId);
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al registrar sesión de resumen");
      }
    },
    [load],
  );

  const upcoming = useMemo(() => {
    const list = exams.filter((e) => e.exam_date >= today).sort((a, b) => a.exam_date.localeCompare(b.exam_date));
    return list.slice(0, 5);
  }, [exams, today]);

  return (
    <Box>
      <PageNav title="Colegio" />

      <Box sx={{ maxWidth: 640, margin: "0 auto", padding: "1.5rem 1rem", pb: BOTTOM_BAR_PADDING }}>
        <SubNav area="colegio" />
        <Typography variant="h4" sx={{ mb: 0.5 }}>
          Colegio
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
            {upcoming.length === 0 && (
              <Alert severity="info" sx={{ borderRadius: 2 }}>
                Todavía no tienes exámenes. Añade uno abajo y Loopy te arma el plan.
              </Alert>
            )}

            {upcoming.map((exam) => {
              const plan = plans[exam.id];
              return (
                <section key={exam.id}>
                  <Typography variant="h6">
                    {exam.subject_name}{" "}
                    <Typography component="span" color="text.secondary">
                      · examen {fmtDate(exam.exam_date)}
                    </Typography>
                  </Typography>
                  {plan && <ExamPlanBlock plan={plan} onToggle={(item) => void togglePlanItem(exam.id, item)} />}
                </section>
              );
            })}

            <Divider />

            <section>
              <Typography variant="h6" sx={{ mb: 1 }}>
                Asignaturas
              </Typography>
              <Box sx={{ mb: 2, border: 1, borderColor: "divider", borderRadius: 2, p: 1.5 }}>
                <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
                  <TextField
                    size="small"
                    placeholder="Nueva asignatura"
                    value={newSubjectName}
                    onChange={(ev) => setNewSubjectName(ev.target.value)}
                    onKeyDown={(ev) => {
                      if (ev.key === "Enter") void addSubject();
                    }}
                    sx={{ flexGrow: 1 }}
                  />
                  <Button variant="contained" onClick={() => void addSubject()} disabled={!newSubjectName.trim()}>
                    Añadir
                  </Button>
                </Stack>
                <PhaseFields value={newPhases} onChange={(patch) => setNewPhases((p) => ({ ...p, ...patch }))} />
              </Box>
              <List sx={{ p: 0 }}>
                {subjects.map((s) => (
                  <Fragment key={s.id}>
                    <ListItem sx={{ border: 1, borderColor: "divider", borderRadius: 2, mb: 0.5 }}>
                    <ListItemText
                      primary={s.name}
                      secondary={
                        s.resumen_total_pages ? (
                          <Box>
                            <LinearProgress
                              variant="determinate"
                              value={Math.min(100, (s.resumen_done_pages / s.resumen_total_pages) * 100)}
                              sx={{ my: 0.5, height: 6, borderRadius: 3 }}
                            />
                            <Typography variant="caption" color="text.secondary">
                              Resumen {s.resumen_done_pages}/{s.resumen_total_pages} hojas
                            </Typography>
                          </Box>
                        ) : (
                          <Typography variant="caption" color="text.secondary">
                            Sin resumen con hojas
                          </Typography>
                        )
                      }
                    />
                    <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
                      {s.resumen_total_pages ? (
                        <Button size="small" onClick={() => void advanceResumen(s.id)}>
                          Sesión
                        </Button>
                      ) : null}
                      <Button
                        size="small"
                        color={editingId === s.id ? "primary" : "inherit"}
                        variant={editingId === s.id ? "outlined" : "text"}
                        onClick={() => startEdit(s)}
                      >
                        {editingId === s.id ? "Cancelar" : "Editar"}
                      </Button>
                    </Stack>
                  </ListItem>
                  {editingId === s.id && editPhases ? (
                    <Box sx={{ border: 1, borderColor: "divider", borderRadius: 2, mb: 0.5, p: 1.5 }}>
                      <PhaseFields value={editPhases} onChange={(patch) => setEditPhases((p) => (p ? { ...p, ...patch } : p))} />
                      <Button variant="contained" size="small" sx={{ mt: 1 }} onClick={() => void saveEdit()}>
                        Guardar
                      </Button>
                    </Box>
                  ) : null}
                  </Fragment>
                ))}
              </List>
            </section>

            <Divider />

            <section>
              <Typography variant="h6" sx={{ mb: 1 }}>
                Nuevo examen
              </Typography>
              <Stack spacing={1.5}>
                <TextField
                  select
                  size="small"
                  label="Asignatura"
                  value={newExamSubject}
                  onChange={(ev) => setNewExamSubject(Number(ev.target.value))}
                >
                  {subjects.map((s) => (
                    <MenuItem key={s.id} value={s.id}>
                      {s.name}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  label="Día del examen"
                  type="date"
                  size="small"
                  value={newExamDate}
                  onChange={(ev) => setNewExamDate(ev.target.value)}
                />
                <Button variant="contained" onClick={() => void addExam()} disabled={!newExamSubject || !newExamDate}>
                  Crear examen
                </Button>
              </Stack>
            </section>
          </Stack>
        )}
      </Box>
    </Box>
  );
}

function ExamPlanBlock({ plan, onToggle }: { plan: ExamPlan; onToggle: (item: PlanItem) => void }) {
  if (plan.items.length === 0) {
    return <Alert severity="warning" sx={{ mt: 1 }}>El plan aún no empieza. Se acerca el día y aparecerá aquí.</Alert>;
  }
  return (
    <List sx={{ p: 0, mt: 1 }}>
      {plan.items.map((item) => (
        <ListItem key={item.date} disablePadding sx={{ mb: 0.5 }}>
          <ListItemButton onClick={() => onToggle(item)} sx={{ borderRadius: 2, border: 1, borderColor: "divider" }}>
            <Checkbox edge="start" checked={item.status === "done"} tabIndex={-1} disableRipple readOnly />
            <ListItemText
              primary={
                <Stack direction="row" spacing={1} alignItems="center">
                  {phaseChip(item.phase)}
                  <Typography variant="body2">
                    {fmtDate(item.date)}
                    {item.status === "skip" ? " · saltado" : ""}
                  </Typography>
                </Stack>
              }
              secondary={item.label ? <Typography variant="body2" color="text.secondary">{item.label}</Typography> : null}
            />
          </ListItemButton>
        </ListItem>
      ))}
    </List>
  );
}
import { useCallback, useEffect, useState } from "react";
import { BOTTOM_BAR_PADDING, PageNav, SubNav } from "../components/Nav";
import { api, examApi, subjectApi, type Exam, type Subject } from "../api/client";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import IconButton from "@mui/material/IconButton";
import Divider from "@mui/material/Divider";

/** Minutos -> "2 h 30 min". Se habla en tiempo, que es como se piensa. */
function duracion(min: number): string {
  if (!min || min < 0) return "—";
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h && m) return `${h} h ${m} min`;
  if (h) return `${h} h`;
  return `${m} min`;
}

function sesiones(total: number, sessionMin: number): string {
  const n = Math.max(1, Math.ceil(total / Math.max(1, sessionMin)));
  return `${n} ${n === 1 ? "sesión" : "sesiones"} de ${sessionMin} min`;
}

const COLORES = [
  "#0288d1",
  "#7b1fa2",
  "#2e7d32",
  "#ef6c00",
  "#c62828",
  "#00838f",
  "#5d4037",
  "#303f9f",
];

export default function Perfil() {
  const [course, setCourse] = useState("");
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [exams, setExams] = useState<Exam[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [nueva, setNueva] = useState("");
  // Último curso confirmado por el servidor, para no reenviarlo en cada blur.
  const [cursoGuardado, setCursoGuardado] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setLoading(true);
    try {
      const [u, subs, ex] = await Promise.all([api.me(), subjectApi.list(), examApi.list()]);
      setCourse(u.course ?? "");
      setCursoGuardado(u.course ?? null);
      setSubjects(subs);
      setExams(ex);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar el perfil");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function guardarCurso() {
    // Guarda solo si cambió: blur y Enter dispara aunque no haya nada nuevo que enviar.
    const valor = course.trim() || null;
    if (valor === cursoGuardado) return;
    setSaving(true);
    try {
      await api.updateMe({ course: valor });
      setCursoGuardado(valor);
      setSaved(true);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar el curso");
    } finally {
      setSaving(false);
    }
  }

  async function crearSubject() {
    const name = nueva.trim();
    if (!name) return;
    // Primer color libre: si no, todas las asignaturas nuevas serían del mismo azul.
    const usados = new Set(subjects.map((s) => s.color));
    const color = COLORES.find((c) => !usados.has(c)) ?? COLORES[0];
    try {
      await subjectApi.create({
        name,
        color,
        prep_minutes: 120,
        session_minutes: 30,
      });
      setNueva("");
      setSubjects(await subjectApi.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear la asignatura");
    }
  }

  async function patchSubject(id: number, patch: Partial<Subject>) {
    try {
      const updated = await subjectApi.update(id, patch);
      setSubjects((prev) => prev.map((s) => (s.id === id ? updated : s)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar la asignatura");
    }
  }

  async function patchExam(id: number, patch: { prep_minutes_override?: number | null }) {
    try {
      const updated = await examApi.update(id, patch);
      setExams((prev) => prev.map((e) => (e.id === id ? updated : e)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar el examen");
    }
  }

  async function borrarSubject(id: number) {
    try {
      await subjectApi.remove(id);
      setSubjects(await subjectApi.list());
      setExams(await examApi.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo eliminar la asignatura");
    }
  }

  if (loading) {
    return (
      <Box>
        <PageNav title="Perfil" />
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      </Box>
    );
  }

  return (
    <Box>
      <PageNav title="Perfil" />

      <Box sx={{ maxWidth: 640, margin: "0 auto", padding: "1.5rem 1rem", pb: BOTTOM_BAR_PADDING }}>
        <SubNav area="colegio" />

        <Typography variant="h4" sx={{ mb: 0.5 }}>
          Perfil
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          El curso y el tiempo que cuesta cada asignatura. Con eso ya se calcula el plan de cada
          examen.
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* ---------------------------------------------------- curso */}
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          Curso
        </Typography>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
          <TextField
            fullWidth
            size="small"
            label="¿En qué curso está?"
            placeholder="4º de Primaria"
            value={course}
            onChange={(e) => {
              setCourse(e.target.value);
              setSaved(false);
            }}
            onBlur={() => void guardarCurso()}
            onKeyDown={(e) => {
              if (e.key === "Enter") void guardarCurso();
            }}
          />
          <Button variant="contained" onClick={() => void guardarCurso()} disabled={saving}>
            Guardar
          </Button>
        </Stack>
        {saved && (
          <Typography variant="caption" color="success.main" sx={{ display: "block", mb: 2 }}>
            Guardado.
          </Typography>
        )}
        {!saved && <Box sx={{ height: 22 }} />}

        <Divider sx={{ my: 2 }} />

        {/* ------------------------------------------- asignaturas */}
        <Typography variant="subtitle1" sx={{ mb: 0.5 }}>
          Asignaturas
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Cuánto cuesta preparar cada una. El plan reparte ese tiempo en días hacia atrás desde el
          examen.
        </Typography>

        <Stack spacing={1.5} sx={{ mb: 2 }}>
          {subjects.map((s) => {
            const usados = s.prep_minutes;
            return (
              <Box key={s.id} sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                  <Box
                    sx={{
                      width: 16,
                      height: 16,
                      borderRadius: "50%",
                      bgcolor: s.color ?? "#bdbdbd",
                      flexShrink: 0,
                      border: s.color ? 0 : 2,
                      borderColor: "text.disabled",
                    }}
                  />
                  <Typography sx={{ fontWeight: 600 }}>{s.name}</Typography>
                  {!s.color && (
                    <Typography variant="caption" color="warning.main">
                      sin color
                    </Typography>
                  )}
                  <IconButton size="small" sx={{ ml: "auto" }} onClick={() => void borrarSubject(s.id)}>
                    <Typography variant="caption" color="text.secondary">
                      quitar
                    </Typography>
                  </IconButton>
                </Stack>

                <Stack direction="row" spacing={0.5} sx={{ mb: 1.25, flexWrap: "wrap" }}>
                  {COLORES.map((c) => (
                    <Box
                      key={c}
                      onClick={() => void patchSubject(s.id, { color: c })}
                      sx={{
                        width: 22,
                        height: 22,
                        borderRadius: "50%",
                        bgcolor: c,
                        cursor: "pointer",
                        border: s.color === c ? 2 : 0,
                        borderColor: "text.primary",
                      }}
                    />
                  ))}
                </Stack>

                <Stack direction="row" spacing={1} alignItems="center">
                  <TextField
                    label="Tiempo total"
                    type="number"
                    size="small"
                    value={usados}
                    onChange={(e) => void patchSubject(s.id, { prep_minutes: Math.max(0, Number(e.target.value) || 0) })}
                    helperText={duracion(usados)}
                    sx={{ flex: 1 }}
                  />
                  <TextField
                    label="Sesión"
                    type="number"
                    size="small"
                    value={s.session_minutes}
                    onChange={(e) => void patchSubject(s.id, { session_minutes: Math.max(5, Number(e.target.value) || 5) })}
                    helperText="minutos"
                    sx={{ width: 120 }}
                  />
                </Stack>
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
                  {sesiones(s.prep_minutes, s.session_minutes)} · {duracion(s.prep_minutes)} en total
                </Typography>
              </Box>
            );
          })}
          {subjects.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              Todavía no hay ninguna asignatura.
            </Typography>
          )}
        </Stack>

        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
          Añadir asignatura
        </Typography>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 3 }}>
          <TextField
            size="small"
            placeholder="Matemáticas"
            value={nueva}
            onChange={(e) => setNueva(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void crearSubject();
            }}
            sx={{ flex: 1 }}
          />
          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
            {`Con el primer color libre`}
          </Typography>
          <Button variant="contained" onClick={() => void crearSubject()} disabled={!nueva.trim()}>
            Añadir
          </Button>
        </Stack>

        <Divider sx={{ my: 2 }} />

        {/* ------------------------------------------ examenes */}
        <Typography variant="subtitle1" sx={{ mb: 0.5 }}>
          Exámenes
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Si un examen concreto necesita más (o menos) de lo normal, se lo dices aquí y solo afecta
          a ese examen.
        </Typography>

        <Stack spacing={1}>
          {exams.map((x) => {
            const base = subjects.find((s) => s.id === x.subject_id);
            return (
              <Box key={x.id} sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                  <Box
                    sx={{
                      width: 16,
                      height: 16,
                      borderRadius: "50%",
                      bgcolor: base?.color ?? "#757575",
                      flexShrink: 0,
                    }}
                  />
                  <Typography sx={{ fontWeight: 600 }}>{base?.name ?? x.subject_name ?? "Asignatura"}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ ml: "auto" }}>
                    {x.exam_date}
                  </Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <TextField
                    label="Este examen necesita"
                    type="number"
                    size="small"
                    value={x.prep_minutes_override ?? ""}
                    placeholder={String(base?.prep_minutes ?? 120)}
                    helperText={
                      x.prep_minutes_override != null
                        ? duracion(x.prep_minutes_override)
                        : `por defecto ${duracion(base?.prep_minutes ?? 120)}`
                    }
                    onChange={(e) => {
                      const raw = e.target.value;
                      const v = raw === "" ? null : Math.max(0, Number(raw) || 0);
                      void patchExam(x.id, { prep_minutes_override: v });
                    }}
                    sx={{ flex: 1 }}
                  />
                  {x.prep_minutes_override != null && (
                    <Button size="small" onClick={() => void patchExam(x.id, { prep_minutes_override: null })}>
                      Quitar
                    </Button>
                  )}
                </Stack>
              </Box>
            );
          })}
          {exams.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              No hay exámenes creados.
            </Typography>
          )}
        </Stack>
      </Box>
    </Box>
  );
}

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { checkinApi, subjectApi, type QuickItem, type QuickItemType, type Subject } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Divider from "@mui/material/Divider";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import FormControlLabel from "@mui/material/FormControlLabel";
import Checkbox from "@mui/material/Checkbox";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import ListItemSecondaryAction from "@mui/material/ListItemSecondaryAction";
import IconButton from "@mui/material/IconButton";
import Chip from "@mui/material/Chip";

const TYPE_LABEL: Record<QuickItemType, string> = {
  deber: "Deber",
  examen: "Examen",
  proyecto: "Proyecto",
};

function todayISO(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function addDays(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

interface Draft {
  key: number;
  item: QuickItem;
}

export default function CheckIn() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [toneTemplate, setToneTemplate] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [type, setType] = useState<QuickItemType>("deber");
  const [title, setTitle] = useState("");
  const [subjectId, setSubjectId] = useState<number>(0);
  const [examDate, setExamDate] = useState(() => addDays(todayISO(), 5));
  const [dueOn, setDueOn] = useState("");
  const [estMinutes, setEstMinutes] = useState<number>(30);
  const [pendingFromClass, setPendingFromClass] = useState(false);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [draftCounter, setDraftCounter] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [subs, tone] = await Promise.all([subjectApi.list(), checkinApi.tone()]);
      setSubjects(subs);
      setToneTemplate(tone.template);
      setSubjectId((cur) => (cur === 0 && subs.length > 0 ? subs[0].id : cur));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar el check-in");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const currentValid = useMemo(() => {
    if (type === "deber" || type === "proyecto") return title.trim().length > 0;
    return subjectId > 0 && !!examDate;
  }, [type, title, subjectId, examDate]);

  const resetForm = () => {
    setTitle("");
    setPendingFromClass(false);
    setEstMinutes(30);
    setDueOn("");
  };

  const buildCurrent = (): QuickItem | null => {
    if (!currentValid) return null;
    const base: QuickItem = { type };
    if (type === "deber") {
      return {
        ...base,
        title: title.trim(),
        subject_id: subjectId > 0 ? subjectId : null,
        est_minutes: estMinutes > 0 ? estMinutes : null,
        pending_from_class: pendingFromClass,
      };
    }
    if (type === "proyecto") {
      return {
        ...base,
        title: title.trim(),
        subject_id: subjectId > 0 ? subjectId : null,
        est_minutes: estMinutes > 0 ? estMinutes : null,
        due_on: dueOn || null,
      };
    }
    return { ...base, subject_id: subjectId, exam_date: examDate };
  };

  const addAnother = () => {
    const item = buildCurrent();
    if (!item) return;
    setDrafts((d) => [...d, { key: draftCounter, item }]);
    setDraftCounter((c) => c + 1);
    resetForm();
  };

  const removeDraft = (key: number) => {
    setDrafts((d) => d.filter((x) => x.key !== key));
  };

  const save = async () => {
    const items = [...drafts.map((d) => d.item)];
    const current = buildCurrent();
    if (current) items.push(current);
    if (items.length === 0) return;
    setSaving(true);
    setError(null);
    try {
      await checkinApi.addItems(items);
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al guardar");
      setSaving(false);
    }
  };

  return (
    <Box>
      <AppBar position="static">
        <Toolbar sx={{ gap: 1 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Loopy · Check-in
          </Typography>
          <Button color="inherit" size="small" component={Link} to="/">
            Mi día
          </Button>
          <Button color="inherit" size="small" component={Link} to="/colegio">
            Colegio
          </Button>
          <Button color="inherit" size="small" onClick={() => void logout()}>
            Salir
          </Button>
        </Toolbar>
      </AppBar>

      <Box sx={{ maxWidth: 640, margin: "0 auto", padding: "1.5rem 1rem" }}>
        <Typography variant="h4" sx={{ mb: 0.5 }}>
          ¿Qué te ponen hoy?
        </Typography>
        {toneTemplate && (
          <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }}>
            Cuando te pregunte, será: «{toneTemplate}»
          </Alert>
        )}
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
              <ToggleButtonGroup
                exclusive
                fullWidth
                value={type}
                onChange={(_, v) => v && setType(v)}
                size="small"
                sx={{ mb: 2 }}
              >
                {(Object.keys(TYPE_LABEL) as QuickItemType[]).map((t) => (
                  <ToggleButton key={t} value={t}>
                    {TYPE_LABEL[t]}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>

              <Stack spacing={1.5}>
                {(type === "deber" || type === "proyecto") && (
                  <TextField
                    label={type === "deber" ? "¿Qué deber te han puesto?" : "Nombre del proyecto"}
                    value={title}
                    onChange={(ev) => setTitle(ev.target.value)}
                    onKeyDown={(ev) => {
                      if (ev.key === "Enter" && currentValid) addAnother();
                    }}
                  />
                )}

                {subjects.length > 0 && (
                  <TextField select label="Asignatura" value={subjectId} onChange={(ev) => setSubjectId(Number(ev.target.value))}>
                    <MenuItem value={0}>Sin asignatura</MenuItem>
                    {subjects.map((s) => (
                      <MenuItem key={s.id} value={s.id}>
                        {s.name}
                      </MenuItem>
                    ))}
                  </TextField>
                )}

                {type === "examen" && (
                  <TextField
                    label="Día del examen"
                    type="date"
                    value={examDate}
                    onChange={(ev) => setExamDate(ev.target.value)}
                  />
                )}

                {type === "proyecto" && (
                  <TextField
                    label="Fecha tope (opcional)"
                    type="date"
                    value={dueOn}
                    onChange={(ev) => setDueOn(ev.target.value)}
                  />
                )}

                {(type === "deber" || type === "proyecto") && (
                  <TextField
                    label="Minutos estimados"
                    type="number"
                    inputProps={{ min: 1 }}
                    value={estMinutes || ""}
                    onChange={(ev) => setEstMinutes(Number(ev.target.value))}
                  />
                )}

                {type === "deber" && (
                  <FormControlLabel
                    control={<Checkbox checked={pendingFromClass} onChange={(ev) => setPendingFromClass(ev.target.checked)} />}
                    label="No me ha dado tiempo en clase"
                  />
                )}

                <Button variant="outlined" onClick={addAnother} disabled={!currentValid}>
                  Añadir otro
                </Button>
              </Stack>
            </section>

            {drafts.length > 0 && (
              <section>
                <Divider sx={{ mb: 1 }} />
                <Typography variant="h6" sx={{ mb: 1 }}>
                  Añadidos ({drafts.length})
                </Typography>
                <List sx={{ p: 0 }}>
                  {drafts.map(({ key, item }) => (
                    <ListItem
                      key={key}
                      sx={{ border: 1, borderColor: "divider", borderRadius: 2, mb: 0.5 }}
                    >
                      <ListItemText
                        primary={
                          item.type === "deber" || item.type === "proyecto" ? item.title : item.exam_date ?? ""
                        }
                        secondary={
                          <Stack direction="row" spacing={1} alignItems="center" component="span">
                            <Chip
                              label={TYPE_LABEL[item.type]}
                              size="small"
                              sx={{ height: 20 }}
                              component="span"
                            />
                            {item.subject_id ? (
                              <Typography component="span" variant="caption" color="text.secondary">
                                {subjects.find((s) => s.id === item.subject_id)?.name}
                              </Typography>
                            ) : null}
                          </Stack>
                        }
                      />
                      <ListItemSecondaryAction>
                        <IconButton size="small" onClick={() => removeDraft(key)} aria-label="Quitar">
                          ✕
                        </IconButton>
                      </ListItemSecondaryAction>
                    </ListItem>
                  ))}
                </List>
              </section>
            )}

            <Button
              variant="contained"
              size="large"
              onClick={() => void save()}
              disabled={saving || (drafts.length === 0 && !currentValid)}
            >
              {saving ? "Guardando…" : "Guardar"}
            </Button>
          </Stack>
        )}
      </Box>
    </Box>
  );
}
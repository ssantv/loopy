import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { summaryApi, type SummaryConfig, type SummaryException } from "../api/client";
import { monthISO, todayISO } from "./today";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Switch from "@mui/material/Switch";
import FormGroup from "@mui/material/FormGroup";
import FormControlLabel from "@mui/material/FormControlLabel";
import TextField from "@mui/material/TextField";
import Checkbox from "@mui/material/Checkbox";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Chip from "@mui/material/Chip";
import Paper from "@mui/material/Paper";
import { DarkModeRounded } from "@mui/icons-material";

const WEEKDAYS = ["L", "M", "X", "J", "V", "S", "D"];

interface DayCell {
  day: number | null;
  iso: string;
  isToday: boolean;
  exc: SummaryException | undefined;
}

export default function Resumen() {
  const { logout } = useAuth();
  const [config, setConfig] = useState<SummaryConfig | null>(null);
  const [month, setMonth] = useState<string>(monthISO());
  const [days, setDays] = useState<SummaryException[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadConfig = useCallback(async () => {
    try {
      setConfig(await summaryApi.config());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar la configuración");
    }
  }, []);

  const loadMonth = useCallback(async () => {
    try {
      const m = await summaryApi.month(month);
      setDays(m.days);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar el mes");
    }
  }, [month]);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadConfig(), loadMonth()]).then(() => setLoading(false));
  }, [loadConfig, loadMonth]);

  const patch = useCallback(
    async (payload: Partial<SummaryConfig>) => {
      try {
        setConfig(await summaryApi.patchConfig(payload));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al guardar");
      }
    },
    [],
  );

  const toggleDay = useCallback(
    async (day: string) => {
      const cur = days.find((d) => d.date === day);
      try {
        if (!cur) {
          const exc: SummaryException = { date: day, action: "skip" };
          setDays((prev) => [...prev, exc].sort((a, b) => a.date.localeCompare(b.date)));
          await summaryApi.putException(day, "skip");
        } else if (cur.action === "skip") {
          const exc: SummaryException = { date: day, action: "add" };
          setDays((prev) => [...prev.filter((d) => d.date !== day), exc].sort((a, b) => a.date.localeCompare(b.date)));
          await summaryApi.putException(day, "add");
        } else {
          setDays((prev) => prev.filter((d) => d.date !== day));
          await summaryApi.deleteException(day);
        }
      } catch (e) {
        await loadMonth();
        setError(e instanceof Error ? e.message : "Error al guardar el día");
      }
    },
    [days, loadMonth],
  );

  const cells = useMemo<DayCell[]>(() => {
    const excByDate = new Map(days.map((d) => [d.date, d]));
    const [y, m] = month.split("-").map(Number);
    const first = new Date(y, m - 1, 1);
    const lead = (first.getDay() + 6) % 7; // lunes=0
    const total = new Date(y, m, 0).getDate();
    const today = todayISO();
    const out: DayCell[] = [];
    for (let i = 0; i < lead; i++) out.push({ day: null, iso: "", isToday: false, exc: undefined });
    for (let d = 1; d <= total; d++) {
      const iso = `${month}-${String(d).padStart(2, "0")}`;
      out.push({ day: d, iso, isToday: iso === today, exc: excByDate.get(iso) });
    }
    return out;
  }, [month, days]);

  const legend = useMemo(() => {
    const counts = { skip: 0, add: 0 };
    for (const d of days) counts[d.action] += 1;
    return counts;
  }, [days]);

  if (loading && !config) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <AppBar position="static">
        <Toolbar sx={{ gap: 1 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Resumen diario
          </Typography>
          <Button color="inherit" size="small" component={Link} to="/">
            Inicio
          </Button>
          <Button color="inherit" size="small" component={Link} to="/casa">
            Hogar
          </Button>
          <Button color="inherit" size="small" component={Link} to="/compra">
            Compra
          </Button>
          <Button color="inherit" size="small" onClick={() => void logout()}>
            Salir
          </Button>
        </Toolbar>
      </AppBar>

      <Box sx={{ maxWidth: 640, margin: "0 auto", padding: "1.5rem 1rem" }}>
        <Stack spacing={3}>
          <Typography variant="h4">Resumen diario</Typography>

          {error && (
            <Alert severity="error" onClose={() => setError(null)}>
              {error}
            </Alert>
          )}

          {config && (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="h6" sx={{ mb: 1 }}>
                Cuándo recibirlo
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1, flexWrap: "wrap" }}>
                <FormControlLabel
                  control={
                    <Switch
                      checked={config.enabled}
                      onChange={(ev) => void patch({ enabled: ev.target.checked })}
                    />
                  }
                  label="Activo"
                />
                <TextField
                  label="Hora"
                  type="time"
                  size="small"
                  value={config.time.slice(0, 5)}
                  onChange={(ev) => {
                    if (ev.target.value) void patch({ time: `${ev.target.value}:00` });
                  }}
                />
              </Stack>
              <FormGroup row>
                {WEEKDAYS.map((label, i) => (
                  <FormControlLabel
                    key={i}
                    control={
                      <Checkbox
                        checked={(config.week_mask & (1 << i)) !== 0}
                        onChange={(ev) => {
                          const mask = ev.target.checked ? config.week_mask | (1 << i) : config.week_mask & ~(1 << i);
                          void patch({ week_mask: mask });
                        }}
                      />
                    }
                    label={label}
                  />
                ))}
              </FormGroup>
            </Paper>
          )}

          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <Button size="small" onClick={() => setMonth(shiftMonth(month, -1))}>
                ←
              </Button>
              <Typography sx={{ flexGrow: 1, textTransform: "capitalize" }}>
                {new Date(month + "-01T00:00:00").toLocaleDateString("es-ES", { month: "long", year: "numeric" })}
              </Typography>
              <Button size="small" onClick={() => setMonth(shiftMonth(month, 1))}>
                →
              </Button>
            </Stack>
            <Stack direction="row" spacing={0.5} sx={{ mb: 0.5 }}>
              {WEEKDAYS.map((label, i) => (
                <Box key={i} sx={{ flex: 1, textAlign: "center" }}>
                  <Typography variant="caption" color="text.secondary">
                    {label}
                  </Typography>
                </Box>
              ))}
            </Stack>
            <Stack direction="row" spacing={0.5} sx={{ flexWrap: "wrap" }}>
              {cells.map((c, i) =>
                c.day === null ? (
                  <Box key={i} sx={{ flex: 1, minWidth: 40, textAlign: "center", height: 40 }} />
                ) : (
                  <Button
                    key={i}
                    size="small"
                    onClick={() => void toggleDay(c.iso)}
                    sx={{
                      flex: 1,
                      minWidth: 40,
                      height: 40,
                      borderRadius: 2,
                      textAlign: "center",
                      fontWeight: c.isToday ? 700 : 400,
                      bgcolor: c.exc ? (c.exc.action === "skip" ? "error.main" : "success.main") : "transparent",
                      color: c.exc ? "common.white" : "text.primary",
                      "&:hover": { opacity: 0.85 },
                      border: c.isToday ? 2 : 1,
                      borderColor: c.isToday ? "primary.main" : "divider",
                    }}
                  >
                    {c.day}
                  </Button>
                ),
              )}
            </Stack>
            <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: "wrap" }}>
              <Chip size="small" label={`Sin resumen · ${legend.skip}`} color="error" variant="outlined" />
              <Chip size="small" label={`Resumen extra · ${legend.add}`} color="success" variant="outlined" />
              <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
                Toca un día para alternar sin → sin resumen → extra.
              </Typography>
            </Stack>
          </Paper>

          <Alert severity="info" sx={{ borderRadius: 2 }}>
            <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
              <DarkModeRounded fontSize="small" />
              <span>
                El resumen llega a la hora marcada con el día resumido: pendientes, compras hechas y de
                mañana. Solo en los días marcados.
              </span>
            </Box>
          </Alert>
        </Stack>
      </Box>
    </Box>
  );
}

function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const total = y * 12 + (m - 1) + delta;
  const ny = Math.floor(total / 12);
  const nm = (total % 12) + 1;
  return `${ny}-${String(nm).padStart(2, "0")}`;
}
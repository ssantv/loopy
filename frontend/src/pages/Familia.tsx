import { useCallback, useEffect, useState } from "react";
import { BOTTOM_BAR_PADDING, PageNav, SubNav } from "../components/Nav";
import { api, type User } from "../api/client";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Divider from "@mui/material/Divider";
import Chip from "@mui/material/Chip";
import PeopleAltOutlinedIcon from "@mui/icons-material/PeopleAltOutlined";

/** El PIN son de 4 a 6 dígitos. */
function pinValido(pin: string): boolean {
  return /^[0-9]{4,6}$/.test(pin);
}

/**
 * Comparación de nombres como la de la entrada del niño: distingue mayúsculas,
 * ignora los espacios de los lados. Así el aviso de duplicado acierta.
 */
function mismoNombre(a: string, b: string): boolean {
  return a.trim().toLocaleLowerCase("es") === b.trim().toLocaleLowerCase("es");
}

function fechaCorta(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" });
}

/**
 * Alta de las cuentas de niño desde la cuenta adulta.
 *
 * El niño no se registra: no tiene email ni contraseña, entra con su nombre y
 * un PIN que elige aquí un adulto. Por eso el PIN se enseña una vez al crearlo
 * y se avisa de que no se puede recuperar: si se pierde, la cuenta se rehace.
 */
export default function Familia() {
  const [children, setChildren] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [pin, setPin] = useState("");
  const [course, setCourse] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [creado, setCreado] = useState<{ nombre: string; pin: string } | null>(null);

  const cargar = useCallback(async () => {
    setLoading(true);
    try {
      setChildren(await api.children());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cargar la familia");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function crear() {
    setError(null);
    setCreado(null);
    if (!pinValido(pin)) {
      setError("El PIN tiene que tener 4 o 6 cifras.");
      return;
    }
    // El nombre es la clave de entrada del niño: si se repite, deja de poder
    // distinguir cuál es cuál, y con dos cuentas que comparten nombre y PIN la
    // entrada se bloquea por completo. Mejor decirlo aquí.
    if (children.some((c) => mismoNombre(c.display_name ?? "", name))) {
      setError(`Ya hay una cuenta con el nombre "${name.trim()}". Usa otro nombre distinto.`);
      return;
    }
    setSaving(true);
    try {
      const nuevo = await api.createChild({
        display_name: name.trim(),
        pin,
        // El backend espera datetime; la fecha del input es un ISO corto.
        birth_date: new Date(birthDate).toISOString(),
        course: course.trim() || null,
      });
      setCreado({ nombre: nuevo.display_name ?? name.trim(), pin });
      setName("");
      setPin("");
      setCourse("");
      setBirthDate("");
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear la cuenta");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Box>
      <PageNav title="Familia" />

      <Box sx={{ maxWidth: 640, margin: "0 auto", padding: "1.5rem 1rem", pb: BOTTOM_BAR_PADDING }}>
        <SubNav area="casa" />

        <Typography variant="h4" sx={{ mb: 0.5 }}>
          Familia
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Aquí se crean las cuentas de los niños. No tienen email: entran con su nombre y un PIN, y
          cada uno tiene su propio colegio, sus deberes y su plan de estudio.
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* ------------------------------------------------- niños dados de alta */}
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          Cuentas de niño
        </Typography>

        {loading ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 3 }}>
            <CircularProgress />
          </Box>
        ) : children.length === 0 ? (
          <Alert severity="info" sx={{ borderRadius: 2, mb: 2 }}>
            Todavía no hay ninguna cuenta de niño. Crea la primera con el formulario de abajo.
          </Alert>
        ) : (
          <Stack spacing={1} sx={{ mb: 2 }}>
            {children.map((c) => (
              <Box key={c.id} sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.5 }}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <PeopleAltOutlinedIcon color="action" />
                  <Typography sx={{ fontWeight: 600 }}>{c.display_name}</Typography>
                  {c.course && (
                    <Chip label={c.course} size="small" sx={{ height: 22 }} />
                  )}
                  {c.age != null && (
                    <Typography variant="caption" color="text.secondary">
                      {c.age} años
                    </Typography>
                  )}
                </Stack>
                <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                  Alta el {fechaCorta(c.created_at)} · entra en /nino con su nombre y su PIN
                </Typography>
              </Box>
            ))}
          </Stack>
        )}

        {creado && (
          <Alert severity="success" sx={{ mb: 2, borderRadius: 2 }}>
            <Typography sx={{ fontWeight: 600 }}>
              {creado.nombre} ya puede entrar con el PIN {creado.pin}
            </Typography>
            <Typography variant="caption" sx={{ display: "block" }}>
              Anótalo: el PIN no se puede recuperar. Si se pierde, hay que crear otra cuenta.
            </Typography>
          </Alert>
        )}

        <Divider sx={{ my: 2 }} />

        {/* --------------------------------------------------------- alta */}
        <Typography variant="subtitle1" sx={{ mb: 0.5 }}>
          Añadir un niño
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Elige un PIN de 4 o 6 cifras que el niño recuerde y que no sea su fecha de cumpleaños.
        </Typography>

        <Stack spacing={1.5}>
          <TextField
            label="Nombre"
            size="small"
            value={name}
            onChange={(e) => setName(e.target.value)}
            helperText="Es el mismo nombre que Teclea para entrar, tal cual."
            required
          />
          <TextField
            label="PIN"
            size="small"
            type="password"
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))}
            error={pin.length > 0 && !pinValido(pin)}
            helperText="4 o 6 cifras."
            inputProps={{ inputMode: "numeric" }}
            required
          />
          <TextField
            label="Fecha de nacimiento"
            type="date"
            size="small"
            value={birthDate}
            onChange={(e) => setBirthDate(e.target.value)}
            helperText="Sirve para adaptar el tono de los avisos a su edad."
            InputLabelProps={{ shrink: true }}
            required
          />
          <TextField
            label="Curso"
            size="small"
            value={course}
            onChange={(e) => setCourse(e.target.value)}
            placeholder="4º de Primaria"
            helperText="Opcional. Aparece en su perfil para tener el contexto a la vista."
          />
          <Button variant="contained" size="large" onClick={() => void crear()} disabled={saving}>
            {saving ? "Creando…" : "Crear cuenta"}
          </Button>
        </Stack>
      </Box>
    </Box>
  );
}

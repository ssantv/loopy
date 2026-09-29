import { useState, type FormEvent } from "react";
import { Navigate, Link as RouterLink, useNavigate } from "react-router-dom";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import SchoolOutlinedIcon from "@mui/icons-material/SchoolOutlined";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Alert from "@mui/material/Alert";
import Link from "@mui/material/Link";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";

/** El PIN son de 4 a 6 dígitos, siempre. Se comprueba antes de llamar a la API. */
function pinValido(pin: string): boolean {
  return /^[0-9]{4,6}$/.test(pin);
}

/**
 * Entrada de los menores: su nombre y su PIN, sin email ni contraseña.
 *
 * Va en su propia pantalla y no como un campo más del login de adulto,
 * porque aquí no hay nada que recordar más que dos cosas: cómo te llamas y
 * tu número. Por eso los rótulos son preguntas, y el botón es grande.
 */
export default function LoginNino() {
  const { user, loginChild } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  // Mientras se escribe, el aviso de "son 4 o 6 cifras" solo molesta. Aparece
  // cuando ya hay algo escrito y sigue sin poder ser un PIN.
  const pinIncompleto = pin.length > 0 && !pinValido(pin);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!pinValido(pin)) {
      setError("El PIN son 4 o 6 cifras.");
      return;
    }
    setSubmitting(true);
    try {
      await loginChild(name.trim(), pin);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error de conexión");
      // Se borra el PIN para que solo haya que escribirlo otra vez, no borrarlo
      // y escribirlo: si se falló, lo que se busca es la siguiente oportunidad.
      setPin("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Box
        component="form"
        onSubmit={onSubmit}
        sx={{ width: 360, mx: 2, display: "flex", flexDirection: "column", gap: 2 }}
      >
        <Avatar sx={{ bgcolor: "primary.main", alignSelf: "center" }}>
          <SchoolOutlinedIcon />
        </Avatar>
        <Typography variant="h5" align="center">
          Loopy
        </Typography>

        {error && <Alert severity="error">{error}</Alert>}

        <TextField
          label="¿Cómo te llamas?"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="username"
          autoFocus
          required
        />
        <TextField
          label="Tu PIN"
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))}
          error={pinIncompleto}
          helperText={pinIncompleto ? "Son 4 o 6 cifras." : "El número que te dio tu madre o tu padre."}
          // Teclado numérico en el móvil, que es donde se usa.
          type="password"
          inputProps={{ inputMode: "numeric", pattern: "[0-9]*", autoComplete: "off" }}
          sx={{ "& input": { letterSpacing: "0.4em", fontSize: "1.3rem", textAlign: "center" } }}
          required
        />
        <Button type="submit" variant="contained" size="large" disabled={submitting}>
          {submitting ? "Entrando…" : "Entrar"}
        </Button>
        <Typography variant="body2" align="center">
          <Link component={RouterLink} to="/login">
            Soy adulto, entrar con mi email
          </Link>
        </Typography>
      </Box>
    </Box>
  );
}

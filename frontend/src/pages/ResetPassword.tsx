import { useState, type FormEvent } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Alert from "@mui/material/Alert";
import Link from "@mui/material/Link";
import { api, ApiError } from "../api/client";

const MIN_LONG = 8;

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [repetir, setRepetir] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [hecho, setHecho] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < MIN_LONG) {
      setError(`La contraseña necesita al menos ${MIN_LONG} caracteres.`);
      return;
    }
    if (password !== repetir) {
      setError("Las dos contraseñas no coinciden.");
      return;
    }
    setSubmitting(true);
    try {
      await api.confirmPasswordReset({ token, new_password: password });
      setHecho(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error de conexión");
    } finally {
      setSubmitting(false);
    }
  };

  // Enlace sin token: no tiene sentido mostrar el formulario.
  if (!token) {
    return (
      <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Box sx={{ width: 360, mx: 2, display: "flex", flexDirection: "column", gap: 2 }}>
          <Alert severity="error">Este enlace no es válido. Pide uno nuevo desde la pantalla de inicio de sesión.</Alert>
          <Typography variant="body2" align="center">
            <Link component={RouterLink} to="/olvide-password">
              Pedir un enlace nuevo
            </Link>
          </Typography>
        </Box>
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Box component="form" onSubmit={onSubmit} sx={{ width: 360, mx: 2, display: "flex", flexDirection: "column", gap: 2 }}>
        <Avatar sx={{ bgcolor: "primary.main", alignSelf: "center" }}>
          <LockOutlinedIcon />
        </Avatar>
        <Typography variant="h5" align="center">
          Elige tu nueva contraseña
        </Typography>
        {hecho ? (
          <>
            <Alert severity="success">Contraseña actualizada. Ya puedes iniciar sesión.</Alert>
            <Button component={RouterLink} to="/login" variant="contained">
              Ir a iniciar sesión
            </Button>
          </>
        ) : (
          <>
            <Typography variant="body2" color="text.secondary">
              Mínimo {MIN_LONG} caracteres. Al cambiarla se cerrarán las sesiones abiertas en otros dispositivos.
            </Typography>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              label="Contraseña nueva"
              type="password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setError(null);
              }}
              autoComplete="new-password"
              required
              autoFocus
            />
            <TextField
              label="Repite la contraseña"
              type="password"
              value={repetir}
              onChange={(e) => {
                setRepetir(e.target.value);
                setError(null);
              }}
              autoComplete="new-password"
              required
              error={repetir.length > 0 && repetir !== password}
              helperText={repetir.length > 0 && repetir !== password ? "No coinciden" : " "}
            />
            <Button type="submit" variant="contained" disabled={submitting}>
              {submitting ? "Guardando…" : "Guardar contraseña"}
            </Button>
          </>
        )}
      </Box>
    </Box>
  );
}

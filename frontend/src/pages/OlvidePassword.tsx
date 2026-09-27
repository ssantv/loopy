import { useState, type FormEvent } from "react";
import { Link as RouterLink } from "react-router-dom";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import MailOutlineIcon from "@mui/icons-material/MailOutline";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Alert from "@mui/material/Alert";
import Link from "@mui/material/Link";
import { api, ApiError } from "../api/client";

export default function OlvidePassword() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviado, setEnviado] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.requestPasswordReset({ email });
      setEnviado(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error de conexión");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Box component="form" onSubmit={onSubmit} sx={{ width: 360, mx: 2, display: "flex", flexDirection: "column", gap: 2 }}>
        <Avatar sx={{ bgcolor: "primary.main", alignSelf: "center" }}>
          <MailOutlineIcon />
        </Avatar>
        <Typography variant="h5" align="center">
          Restablecer contraseña
        </Typography>
        {enviado ? (
          <Alert severity="success">
            Si el email existe, te hemos enviado un enlace para elegir una contraseña nueva. Revisa también la
            carpeta de spam.
          </Alert>
        ) : (
          <>
            <Typography variant="body2" color="text.secondary">
              Escribe el email de tu cuenta y te enviaremos un enlace para poner una contraseña nueva.
            </Typography>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              label="Email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              autoFocus
            />
            <Button type="submit" variant="contained" disabled={submitting}>
              {submitting ? "Enviando…" : "Enviar enlace"}
            </Button>
          </>
        )}
        <Typography variant="body2" align="center">
          ¿Te has acordado?{" "}
          <Link component={RouterLink} to="/login">
            Volver a iniciar sesión
          </Link>
        </Typography>
      </Box>
    </Box>
  );
}

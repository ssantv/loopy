import { useState, type FormEvent } from "react";
import { Navigate, Link as RouterLink, useNavigate } from "react-router-dom";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import PersonAddOutlinedIcon from "@mui/icons-material/PersonAddOutlined";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Alert from "@mui/material/Alert";
import Link from "@mui/material/Link";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";

/**
 * Alta de cuenta adulta.
 *
 * Aquí no se ofrece el perfil de niño: los menores no se registran, los da de
 * alta un adulto con un PIN desde Casa → Familia. Es la única forma de crear
 * esa cuenta a propósito, para que un niño no acabe con un email que hay que
 * recordar y que nadie le va a decir.
 */
export default function Register() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [timezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register({ email, password, timezone });
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error de conexión");
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
        <Avatar sx={{ bgcolor: "secondary.main", alignSelf: "center" }}>
          <PersonAddOutlinedIcon />
        </Avatar>
        <Typography variant="h5" align="center">
          Crea tu cuenta Loopy
        </Typography>
        <Typography variant="body2" align="center" color="text.secondary">
          Para llevar la casa. Los niños no se registran: les creas su cuenta con un PIN.
        </Typography>
        {error && <Alert severity="error">{error}</Alert>}
        <TextField
          label="Email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
        />
        <TextField
          label="Contraseña (mín. 8 caracteres)"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
          required
          helperText="Argon2id, nunca se guarda en claro."
        />
        <Button type="submit" variant="contained" disabled={submitting}>
          {submitting ? "Creando…" : "Crear cuenta"}
        </Button>
        <Typography variant="body2" align="center">
          ¿Ya tienes cuenta?{" "}
          <Link component={RouterLink} to="/login">
            Entra
          </Link>
        </Typography>
      </Box>
    </Box>
  );
}

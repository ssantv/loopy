import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Alert from "@mui/material/Alert";
import Link from "@mui/material/Link";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate("/", { replace: true });
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
          <LockOutlinedIcon />
        </Avatar>
        <Typography variant="h5" align="center">
          Inicia sesión en Loopy
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
          label="Contraseña"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
        <Button type="submit" variant="contained" disabled={submitting}>
          {submitting ? "Entrando…" : "Entrar"}
        </Button>
        <Typography variant="body2" align="center">
          ¿No tienes cuenta? <Link href="/registro">Regístrate</Link>
        </Typography>
      </Box>
    </Box>
  );
}
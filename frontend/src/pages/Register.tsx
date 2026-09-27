import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import PersonAddOutlinedIcon from "@mui/icons-material/PersonAddOutlined";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Alert from "@mui/material/Alert";
import Link from "@mui/material/Link";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";

export default function Register() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [profileType, setProfileType] = useState("adult");
  const [birthDate, setBirthDate] = useState("");
  const [timezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register({
        email,
        password,
        profile_type: profileType,
        timezone,
        ...(profileType === "child" ? { birth_date: new Date(birthDate).toISOString() } : {}),
      });
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
        <Avatar sx={{ bgcolor: "secondary.main", alignSelf: "center" }}>
          <PersonAddOutlinedIcon />
        </Avatar>
        <Typography variant="h5" align="center">
          Crea tu cuenta Loopy
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
        <FormControl>
          <InputLabel id="profile-type-label">Tipo de cuenta</InputLabel>
          <Select
            labelId="profile-type-label"
            label="Tipo de cuenta"
            value={profileType}
            onChange={(e) => setProfileType(e.target.value)}
          >
            <MenuItem value="adult">Adulto</MenuItem>
            <MenuItem value="child">Niño</MenuItem>
          </Select>
        </FormControl>
        {profileType === "child" && (
          <TextField
            label="Fecha de nacimiento (para el tono)"
            type="date"
            value={birthDate}
            onChange={(e) => setBirthDate(e.target.value)}
            required
          />
        )}
        <Button type="submit" variant="contained" disabled={submitting}>
          {submitting ? "Creando…" : "Crear cuenta"}
        </Button>
        <Typography variant="body2" align="center">
          ¿Ya tienes cuenta? <Link href="/login">Entra</Link>
        </Typography>
      </Box>
    </Box>
  );
}
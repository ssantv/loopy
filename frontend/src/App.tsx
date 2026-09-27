import { Navigate, Route, Routes } from "react-router-dom";
import CircleProgress from "@mui/material/CircularProgress";
import Box from "@mui/material/Box";
import { useAuth } from "./auth/AuthContext";
import Login from "./pages/Login";
import Register from "./pages/Register";
import OlvidePassword from "./pages/OlvidePassword";
import ResetPassword from "./pages/ResetPassword";
import Home from "./pages/Home";
import Colegio from "./pages/Colegio";
import CheckIn from "./pages/CheckIn";
import Casa from "./pages/Casa";
import Compra from "./pages/Compra";
import Resumen from "./pages/Resumen";
import Pendientes from "./pages/Pendientes";
import Menu from "./pages/Menu";
import Calendario from "./pages/Calendario";

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <CircleProgress />
      </Box>
    );
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function ChildOnly({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <CircleProgress />
      </Box>
    );
  if (!user || user.profile_type !== "child") return <Navigate to="/" replace />;
  return <>{children}</>;
}

function AdultOnly({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <CircleProgress />
      </Box>
    );
  if (!user || user.profile_type !== "adult") return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/registro" element={<Register />} />
      <Route path="/olvide-password" element={<OlvidePassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/" element={<Protected>{<Home />}</Protected>} />
      <Route path="/colegio" element={<ChildOnly>{<Colegio />}</ChildOnly>} />
      <Route path="/checkin" element={<ChildOnly>{<CheckIn />}</ChildOnly>} />
      <Route path="/casa" element={<AdultOnly>{<Casa />}</AdultOnly>} />
      <Route path="/compra" element={<AdultOnly>{<Compra />}</AdultOnly>} />
      <Route path="/resumen" element={<AdultOnly>{<Resumen />}</AdultOnly>} />
      <Route path="/menu" element={<AdultOnly>{<Menu />}</AdultOnly>} />
      <Route path="/pendientes" element={<Protected>{<Pendientes />}</Protected>} />
      <Route path="/calendario" element={<Protected>{<Calendario />}</Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
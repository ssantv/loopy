import { Navigate, Route, Routes } from "react-router-dom";
import CircleProgress from "@mui/material/CircularProgress";
import Box from "@mui/material/Box";
import { useAuth } from "./auth/AuthContext";
import { isChildProfile } from "./components/Nav";
import Login from "./pages/Login";
import LoginNino from "./pages/LoginNino";
import Register from "./pages/Register";
import OlvidePassword from "./pages/OlvidePassword";
import ResetPassword from "./pages/ResetPassword";
import Home from "./pages/Home";
import Colegio from "./pages/Colegio";
import CheckIn from "./pages/CheckIn";
import Perfil from "./pages/Perfil";
import Casa from "./pages/Casa";
import Familia from "./pages/Familia";
import Compra from "./pages/Compra";
import Resumen from "./pages/Resumen";
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
  if (!user || !isChildProfile(user.profile_type)) return <Navigate to="/" replace />;
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
  if (!user || isChildProfile(user.profile_type)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/nino" element={<LoginNino />} />
      <Route path="/registro" element={<Register />} />
      <Route path="/olvide-password" element={<OlvidePassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/" element={<Protected>{<Home />}</Protected>} />
      <Route path="/colegio" element={<ChildOnly>{<Colegio />}</ChildOnly>} />
      <Route path="/checkin" element={<ChildOnly>{<CheckIn />}</ChildOnly>} />
      <Route path="/perfil" element={<ChildOnly>{<Perfil />}</ChildOnly>} />
      <Route path="/casa" element={<AdultOnly>{<Casa />}</AdultOnly>} />
      <Route path="/compra" element={<AdultOnly>{<Compra />}</AdultOnly>} />
      <Route path="/resumen" element={<AdultOnly>{<Resumen />}</AdultOnly>} />
      <Route path="/menu" element={<AdultOnly>{<Menu />}</AdultOnly>} />
      <Route path="/familia" element={<AdultOnly>{<Familia />}</AdultOnly>} />
      <Route path="/pendientes" element={<Navigate to="/" replace />} />
      <Route path="/calendario" element={<Protected>{<Calendario />}</Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
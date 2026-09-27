import { useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Paper from "@mui/material/Paper";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import ListItemIcon from "@mui/material/ListItemIcon";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";
import HomeIcon from "@mui/icons-material/Home";
import CalendarMonthIcon from "@mui/icons-material/CalendarMonth";
import SchoolIcon from "@mui/icons-material/School";
import CottageIcon from "@mui/icons-material/Cottage";
import LogoutIcon from "@mui/icons-material/Logout";
import PersonIcon from "@mui/icons-material/Person";

/** Altura reservada para la barra inferior en movil, para que no tape el contenido. */
export const BOTTOM_BAR_PADDING = "calc(72px + env(safe-area-inset-bottom))";

/** El perfil se guarda como texto libre, asi que aceptamos los valores antiguos. */
export function isChildProfile(profileType: string | undefined | null): boolean {
  return profileType === "child" || profileType === "nino";
}

export function useIsChild(): boolean {
  const { user } = useAuth();
  return isChildProfile(user?.profile_type);
}

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
}

/**
 * Solo tres destinos de primer nivel, siempre los mismos y siempre en el
 * mismo orden. "Mi dia" esta en todas las pantallas: es la puerta de entrada
 * y la marca de donde estas.
 */
function topLevelItems(isChild: boolean): NavItem[] {
  return [
    { to: "/", label: "Mi día", icon: <HomeIcon /> },
    isChild
      ? { to: "/colegio", label: "Colegio", icon: <SchoolIcon /> }
      : { to: "/casa", label: "Casa", icon: <CottageIcon /> },
    { to: "/calendario", label: "Calendario", icon: <CalendarMonthIcon /> },
  ];
}

/** Paginas que cuelgan del area: no van en la barra, van en su subnavegacion. */
export function subItems(isChild: boolean): NavItem[] {
  if (isChild) {
    return [
      { to: "/colegio", label: "Colegio", icon: <SchoolIcon /> },
      { to: "/checkin", label: "Check-in", icon: <PersonIcon /> },
    ];
  }
  return [
    { to: "/casa", label: "Casa", icon: <CottageIcon /> },
    { to: "/menu", label: "Menú", icon: <PersonIcon /> },
    { to: "/compra", label: "Compra", icon: <PersonIcon /> },
    { to: "/resumen", label: "Resumen", icon: <PersonIcon /> },
  ];
}

function isActive(pathname: string, to: string): boolean {
  return to === "/" ? pathname === "/" : pathname === to;
}

/**
 * Cabecera comun: titulo de la pagina (para saber donde estas siempre) y menu
 * de usuario con "Salir", que deja de competir con la navegacion.
 * En movil los tres destinos pasan a una barra fija abajo, al alcance del
 * pulgar; en escritorio se quedan en la cabecera.
 */
export function PageNav({ title }: { title: string }) {
  const { user, logout } = useAuth();
  const isChild = useIsChild();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const { pathname } = useLocation();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const items = topLevelItems(isChild);

  return (
    <>
      <AppBar position="static" color="default">
        <Toolbar sx={{ gap: 1 }}>
          <Typography variant="h6" sx={{ flexGrow: 1, minWidth: 0 }} noWrap>
            {title}
          </Typography>

          {!isMobile && (
            <Box sx={{ display: "flex", gap: 0.5 }}>
              {items.map((it) => {
                const active = isActive(pathname, it.to);
                return (
                  <Button
                    key={it.to}
                    component={Link}
                    to={it.to}
                    size="small"
                    startIcon={it.icon}
                    aria-current={active ? "page" : undefined}
                    sx={{
                      bgcolor: active ? "primary.main" : "transparent",
                      color: active ? "primary.contrastText" : "text.primary",
                      "&:hover": { bgcolor: active ? "primary.dark" : "action.hover" },
                    }}
                  >
                    {it.label}
                  </Button>
                );
              })}
            </Box>
          )}

          <IconButton onClick={(e) => setAnchor(e.currentTarget)} aria-label="Menú de cuenta" size="small">
            <PersonIcon />
          </IconButton>
          <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
            <MenuItem disabled sx={{ opacity: "1 !important" }}>
              <Typography variant="body2" noWrap>
                {user?.display_name ?? user?.email}
              </Typography>
            </MenuItem>
            <MenuItem
              onClick={() => {
                setAnchor(null);
                void logout();
              }}
            >
              <ListItemIcon>
                <LogoutIcon fontSize="small" />
              </ListItemIcon>
              Salir
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>

      {isMobile && (
        <Paper
          elevation={8}
          sx={{
            position: "fixed",
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: (t) => t.zIndex.appBar,
            display: "flex",
            borderTop: 1,
            borderColor: "divider",
            pb: "env(safe-area-inset-bottom)",
          }}
        >
          {items.map((it) => {
            const active = isActive(pathname, it.to);
            return (
              <Button
                key={it.to}
                component={Link}
                to={it.to}
                aria-current={active ? "page" : undefined}
                sx={{
                  flex: 1,
                  minWidth: 0,
                  py: 1,
                  borderRadius: 0,
                  flexDirection: "column",
                  gap: 0,
                  color: active ? "primary.main" : "text.secondary",
                  bgcolor: active ? "action.selected" : "transparent",
                }}
              >
                {it.icon}
                <Typography variant="caption" sx={{ mt: 0.25, fontWeight: active ? 700 : 400 }}>
                  {it.label}
                </Typography>
              </Button>
            );
          })}
        </Paper>
      )}
    </>
  );
}

/**
 * Navegacion secundaria dentro de un area (Casa/Menu/Compra/Resumen, Colegio/Check-in).
 * No se muestra en la pagina principal del area: la barra de abajo ya dice
 * "Colegio"/"Casa" y activa, asi que repetirlo solo seria ruido.
 */
export function SubNav({ area }: { area: "casa" | "colegio" }) {
  const { pathname } = useLocation();
  const items = subItems(area === "colegio");
  if (pathname === items[0].to) return null;

  return (
    <Box
      sx={{
        display: "flex",
        gap: 0.5,
        overflowX: "auto",
        pb: 0.5,
        mb: 2,
        borderBottom: 1,
        borderColor: "divider",
      }}
    >
      {items.map((it) => {
        const active = isActive(pathname, it.to);
        return (
          <Button
            key={it.to}
            component={Link}
            to={it.to}
            size="small"
            aria-current={active ? "page" : undefined}
            sx={{
              flexShrink: 0,
              borderRadius: 2,
              bgcolor: active ? "primary.main" : "action.hover",
              color: active ? "primary.contrastText" : "text.primary",
              "&:hover": { bgcolor: active ? "primary.dark" : "action.selected" },
            }}
          >
            {it.label}
          </Button>
        );
      })}
    </Box>
  );
}

import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#2e7d32" },
    secondary: { main: "#ef6c00" },
    background: { default: "#f7f9f7" },
  },
  shape: { borderRadius: 12 },
});

export default theme;
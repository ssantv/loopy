import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { shoppingApi, type ShoppingItem, type ShoppingRecommend } from "../api/client";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import ListItemSecondaryAction from "@mui/material/ListItemSecondaryAction";
import Chip from "@mui/material/Chip";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import IconButton from "@mui/material/IconButton";
import DeleteIcon from "@mui/icons-material/Delete";
import HistoryIcon from "@mui/icons-material/History";

export default function Compra() {
  const { logout } = useAuth();
  const [items, setItems] = useState<ShoppingItem[]>([]);
  const [recs, setRecs] = useState<ShoppingRecommend[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [qty, setQty] = useState("");
  const [boughtOpen, setBoughtOpen] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, recommendations] = await Promise.all([shoppingApi.list(), shoppingApi.recommend()]);
      setItems(list);
      setRecs(recommendations);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar la compra");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const addItem = useCallback(
    async (n: string, q: string) => {
      const name = n.trim();
      if (!name) return;
      try {
        await shoppingApi.create({ name, qty: q.trim() || null });
        setName("");
        setQty("");
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al añadir");
      }
    },
    [load],
  );

  const toggle = useCallback(
    async (item: ShoppingItem) => {
      try {
        if (item.purchased) {
          await shoppingApi.unpurchase(item.id);
        } else {
          await shoppingApi.purchase(item.id);
        }
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al actualizar");
      }
    },
    [load],
  );

  const remove = useCallback(
    async (item: ShoppingItem) => {
      try {
        await shoppingApi.remove(item.id);
        await load();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error al quitar");
      }
    },
    [load],
  );

  if (loading && items.length === 0) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  const pending = items.filter((i) => !i.purchased);
  const bought = items.filter((i) => i.purchased);

  return (
    <Box>
      <AppBar position="static">
        <Toolbar sx={{ gap: 1 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Lista de la compra
          </Typography>
          <Button color="inherit" size="small" component={Link} to="/">
            Inicio
          </Button>
          <Button color="inherit" size="small" component={Link} to="/casa">
            Hogar
          </Button>
          <Button color="inherit" size="small" component={Link} to="/resumen">
            Resumen
          </Button>
          <Button color="inherit" size="small" onClick={() => void logout()}>
            Salir
          </Button>
        </Toolbar>
      </AppBar>

      <Box sx={{ maxWidth: 640, margin: "0 auto", padding: "1.5rem 1rem" }}>
        <Typography variant="h4" sx={{ mb: 2 }}>
          Compra
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Stack spacing={3}>
          <section>
            <Typography variant="h6" sx={{ mb: 1 }}>
              Añadir
            </Typography>
            <Stack direction="row" spacing={1}>
              <TextField
                size="small"
                placeholder="Qué comprar…"
                value={name}
                onChange={(ev) => setName(ev.target.value)}
                onKeyDown={(ev) => {
                  if (ev.key === "Enter") void addItem(name, qty);
                }}
                sx={{ flexGrow: 1 }}
              />
              <TextField
                size="small"
                placeholder="Cantidad"
                value={qty}
                onChange={(ev) => setQty(ev.target.value)}
                onKeyDown={(ev) => {
                  if (ev.key === "Enter") void addItem(name, qty);
                }}
                sx={{ width: 110 }}
              />
              <Button variant="contained" onClick={() => void addItem(name, qty)} disabled={!name.trim()}>
                Añadir
              </Button>
            </Stack>
          </section>

          {recs.length > 0 && (
            <section>
              <Typography variant="h6" sx={{ mb: 1 }}>
                Recomendado (compras recientes)
              </Typography>
              <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
                {recs.map((r) => (
                  <Chip
                    key={r.name}
                    label={`${r.name}${r.qty ? ` · ${r.qty}` : ""} (×${r.count})`}
                    color="primary"
                    variant="outlined"
                    onClick={() => void addItem(r.name, r.qty ?? "")}
                  />
                ))}
              </Stack>
            </section>
          )}

          <section>
            <Typography variant="h6" sx={{ mb: 1 }}>
              Pendiente ({pending.length})
            </Typography>
            {pending.length === 0 ? (
              <Alert severity="success" sx={{ borderRadius: 2 }}>
                Sin pendientes.
              </Alert>
            ) : (
              <List sx={{ p: 0 }}>
                {pending.map((item) => (
                  <ListItem key={item.id} disablePadding sx={{ mb: 0.5 }}>
                    <ListItemButton
                      onClick={() => void toggle(item)}
                      sx={{ borderRadius: 2, border: 1, borderColor: "divider" }}
                    >
                      <Checkbox edge="start" checked={false} tabIndex={-1} disableRipple readOnly />
                      <ListItemText primary={item.name} secondary={item.qty ?? undefined} />
                    </ListItemButton>
                    <ListItemSecondaryAction>
                      <IconButton edge="end" size="small" onClick={() => void remove(item)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </ListItemSecondaryAction>
                  </ListItem>
                ))}
              </List>
            )}
          </section>

          {bought.length > 0 && (
            <section>
              <Button
                fullWidth
                onClick={() => setBoughtOpen((v) => !v)}
                sx={{ justifyContent: "space-between", textTransform: "none" }}
              >
                <span>✓ Compradas ({bought.length})</span>
                <span>{boughtOpen ? "▴" : "▾"}</span>
              </Button>
              <List sx={{ p: 0 }}>
                {bought.map((item) => (
                  <ListItem key={item.id} disablePadding sx={{ mb: 0.5 }} dense>
                    <ListItemButton
                      onClick={() => void toggle(item)}
                      sx={{ borderRadius: 2, opacity: 0.65, "& .MuiListItemButton-root": {} }}
                    >
                      <Checkbox edge="start" checked tabIndex={-1} disableRipple readOnly />
                      <ListItemText primary={item.name} secondary={item.qty ?? undefined} />
                    </ListItemButton>
                    <ListItemSecondaryAction>
                      <HistoryIcon fontSize="small" color="disabled" sx={{ mr: 1, verticalAlign: "middle" }} />
                    </ListItemSecondaryAction>
                  </ListItem>
                ))}
              </List>
            </section>
          )}
        </Stack>
      </Box>
    </Box>
  );
}
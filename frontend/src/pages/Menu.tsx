import { useCallback, useEffect, useMemo, useState } from "react";
import { BOTTOM_BAR_PADDING, PageNav, SubNav } from "../components/Nav";
import { menuApi, type Category, type Goal, type MealPlanItem, type RecipeBack, type SlotConfig } from "../api/client";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import IconButton from "@mui/material/IconButton";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import EditIcon from "@mui/icons-material/Edit";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import FormControlLabel from "@mui/material/FormControlLabel";
import Switch from "@mui/material/Switch";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";

const SLOT_NAMES: Record<string, string> = {
  desayuno: "Desayuno",
  almuerzo: "Almuerzo",
  comida: "Comida",
  merienda: "Merienda",
  cena: "Cena",
};

const SLOT_ORDER = ["desayuno", "almuerzo", "comida", "merienda", "cena"];

function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function mondayOf(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function labelOf(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("es-ES", { day: "numeric", month: "short" });
}

function weekdayOf(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("es-ES", { weekday: "short" });
}

function cellKey(day: string, slot: string): string {
  return `${day}|${slot}`;
}

export default function Menu() {
  const [tab, setTab] = useState(0);
  const [start, setStart] = useState<string>(() => mondayOf(new Date().toISOString().slice(0, 10)));
  const [slots, setSlots] = useState<SlotConfig[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [recipes, setRecipes] = useState<RecipeBack[]>([]);
  const [plans, setPlans] = useState<MealPlanItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [assign, setAssign] = useState<{ day: string; slot: string; current: MealPlanItem | null } | null>(null);
  const [recipeDlg, setRecipeDlg] = useState<{ open: boolean; RecipeBack: RecipeBack | null }>({ open: false, RecipeBack: null });
  const [newCat, setNewCat] = useState("");

  const planMap = useMemo(() => {
    const m: Record<string, MealPlanItem> = {};
    for (const p of plans) m[cellKey(p.date, p.slot)] = p;
    return m;
  }, [plans]);

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(start, i)), [start]);

  const setErr = useCallback((e: unknown) => {
    setError(e instanceof Error ? e.message : "Error inesperado");
  }, []);

  const loadMeta = useCallback(async () => {
    const [s, c, g, r] = await Promise.all([
      menuApi.slots(),
      menuApi.categories(),
      menuApi.goals(),
      menuApi.recipes(),
    ]);
    setSlots(s.slots);
    setCategories(c);
    setGoals(g);
    setRecipes(r);
  }, []);

  const loadPlan = useCallback(async () => {
    const w = await menuApi.plan(start);
    setPlans(w.plans);
  }, [start]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([loadMeta(), loadPlan()]);
    } catch (e) {
      setErr(e);
    } finally {
      setLoading(false);
    }
  }, [loadMeta, loadPlan, setErr]);

  useEffect(() => {
    void load();
  }, [load]);

  const showMsg = useCallback((m: string) => {
    setMsg(m);
    window.setTimeout(() => setMsg(null), 4000);
  }, []);

  const toggleSlot = useCallback(
    async (config: SlotConfig) => {
      try {
        await menuApi.patchSlot(config.slot, { enabled: !config.enabled });
        await loadMeta();
        if (config.enabled) showMsg("Franja desactivada");
        else showMsg("Franja activada");
      } catch (e) {
        setErr(e);
      }
    },
    [loadMeta, setErr, showMsg],
  );

  const copyWeek = useCallback(async () => {
    try {
      const res = await menuApi.copyWeek(addDays(start, -7), start);
      showMsg(`${res.copied} asignaciones copiadas de la semana anterior`);
      await loadPlan();
    } catch (e) {
      setErr(e);
    }
  }, [start, loadPlan, setErr, showMsg]);

  const recommend = useCallback(async () => {
    try {
      const res = await menuApi.recommend(start);
      showMsg(res.filled > 0 ? `${res.filled} huecos rellenados` : "No hay huecos libres para rellenar");
      await loadPlan();
    } catch (e) {
      setErr(e);
    }
  }, [start, loadPlan, setErr, showMsg]);

  const addWeek = useCallback(async () => {
    try {
      const res = await menuApi.addWeekToShopping(start);
      showMsg(`${res.created} aÃ±adidos y ${res.updated} actualizados en la compra`);
    } catch (e) {
      setErr(e);
    }
  }, [start, setErr, showMsg]);

  const addRecipeShopping = useCallback(
    async (recipeId: number) => {
      try {
        const res = await menuApi.addRecipeToShopping(recipeId);
        showMsg(`${res.created} aÃ±adidos y ${res.updated} actualizados en la compra`);
      } catch (e) {
        setErr(e);
      }
    },
    [setErr, showMsg],
  );

  const saveAssign = useCallback(
    async (day: string, slot: string, payload: { recipe_id: number | null; free_text: string | null }) => {
      try {
        await menuApi.setPlan(day, slot, payload);
        setAssign(null);
        await loadPlan();
      } catch (e) {
        setErr(e);
      }
    },
    [loadPlan, setErr],
  );

  const clearCell = useCallback(
    async (day: string, slot: string) => {
      try {
        await menuApi.clearPlan(day, slot);
        setAssign(null);
        await loadPlan();
      } catch (e) {
        setErr(e);
      }
    },
    [loadPlan, setErr],
  );

  const savedRecipe = useCallback(async () => {
    setRecipeDlg({ open: false, RecipeBack: null });
    try {
      await Promise.all([loadMeta(), recipes.length === 0 ? Promise.resolve() : loadMeta()]);
    } catch (e) {
      setErr(e);
    }
  }, [loadMeta, setErr, recipes.length]);

  if (loading && recipes.length === 0) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <PageNav title="Menú" />


      <Box sx={{ maxWidth: 920, margin: "0 auto", padding: "1.5rem 1rem", pb: BOTTOM_BAR_PADDING }}>
        <SubNav area="casa" />
        <Typography variant="h4" sx={{ mb: 0.5 }}>
          MenÃº semanal
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          Planifica comidas para toda la semana, usa recetas en la compra y cubre tus objetivos.
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}
        {msg && (
          <Alert severity="info" sx={{ mb: 2 }} onClose={() => setMsg(null)}>
            {msg}
          </Alert>
        )}

        <Tabs value={tab} onChange={(_e, v) => setTab(v)} sx={{ mb: 2 }}>
          <Tab label="Plan semanal" />
          <Tab label="Recetas" />
          <Tab label="CategorÃ­as" />
        </Tabs>

        {tab === 0 && (
          <PlanTab
            start={start}
            days={days}
            planMap={planMap}
            slots={slots}
            recipes={recipes}
            onPrev={() => setStart(mondayOf(addDays(start, -7)))}
            onNext={() => setStart(mondayOf(addDays(start, 7)))}
            onAssign={setAssign}
            onCopy={copyWeek}
            onRecommend={recommend}
            onAddWeek={addWeek}
          />
        )}

        {tab === 1 && (
          <RecipesTab
            categories={categories}
            recipes={recipes}
            onNew={() => setRecipeDlg({ open: true, RecipeBack: null })}
            onEdit={(r) => setRecipeDlg({ open: true, RecipeBack: r })}
            onDelete={async (id) => {
              try {
                await menuApi.removeRecipe(id);
                await loadMeta();
              } catch (e) {
                setErr(e);
              }
            }}
            onAddShopping={addRecipeShopping}
          />
        )}

        {tab === 2 && (
          <CategoriesTab
            slots={slots}
            categories={categories}
            goals={goals}
            onToggleSlot={toggleSlot}
            onNewCategory={async () => {
              const name = newCat.trim();
              if (!name) return;
              try {
                await menuApi.createCategory(name);
                setNewCat("");
                await loadMeta();
              } catch (e) {
                setErr(e);
              }
            }}
            newCat={newCat}
            setNewCat={setNewCat}
            onSaveGoal={async (g) => {
              try {
                await menuApi.patchGoal(g.category_id, {
                  min_per_week: g.min_per_week,
                  max_per_week: g.max_per_week,
                });
                await loadMeta();
                showMsg("Objetivo guardado");
              } catch (e) {
                setErr(e);
              }
            }}
            onDeleteCategory={async (id) => {
              try {
                await menuApi.removeCategory(id);
                await loadMeta();
              } catch (e) {
                setErr(e);
              }
            }}
          />
        )}
      </Box>

      {assign && (
        <AssignDialog
          day={assign.day}
          slot={assign.slot}
          current={assign.current}
          recipes={recipes}
          onClose={() => setAssign(null)}
          onSave={saveAssign}
          onClear={clearCell}
        />
      )}

      {recipeDlg.open && (
        <RecipeDialog
          RecipeBack={recipeDlg.RecipeBack}
          categories={categories}
          onClose={() => setRecipeDlg({ open: false, RecipeBack: null })}
          onSaved={savedRecipe}
        />
      )}
    </Box>
  );
}

function PlanTab({
  start,
  days,
  planMap,
  slots,
  recipes,
  onPrev,
  onNext,
  onAssign,
  onCopy,
  onRecommend,
  onAddWeek,
}: {
  start: string;
  days: string[];
  planMap: Record<string, MealPlanItem>;
  slots: SlotConfig[];
  recipes: RecipeBack[];
  onPrev: () => void;
  onNext: () => void;
  onAssign: (a: { day: string; slot: string; current: MealPlanItem | null }) => void;
  onCopy: () => void;
  onRecommend: () => void;
  onAddWeek: () => void;
}) {
  const enabled = useMemo(() => new Set(slots.filter((s) => s.enabled).map((s) => s.slot)), [slots]);
  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ flexWrap: "wrap" }}>
        <IconButton aria-label="semana anterior" onClick={onPrev} size="small">
          <ChevronLeftIcon />
        </IconButton>
        <Typography variant="subtitle1" sx={{ minWidth: 150, textAlign: "center" }}>
          {labelOf(days[0])} â€“ {labelOf(days[6])}
        </Typography>
        <IconButton aria-label="semana siguiente" onClick={onNext} size="small">
          <ChevronRightIcon />
        </IconButton>
        <Box sx={{ flexGrow: 1 }} />
        <Button size="small" onClick={onCopy}>
          Copiar semana anterior
        </Button>
        <Button size="small" variant="outlined" onClick={onRecommend} disabled={recipes.length === 0}>
          Recomendar huecos
        </Button>
        <Button size="small" variant="contained" onClick={onAddWeek}>
          AÃ±adir a la compra
        </Button>
      </Stack>

      <Box sx={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 640 }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: "6px" }} />
              {days.map((d) => (
                <th key={d} style={{ textAlign: "center", padding: "6px" }}>
                  <Typography variant="caption" color="text.secondary">
                    {weekdayOf(d)}
                  </Typography>
                  <br />
                  <Typography variant="body2" fontWeight="bold">
                    {labelOf(d)}
                  </Typography>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SLOT_ORDER.map((slot) => {
              const active = enabled.has(slot);
              return (
                <tr key={slot}>
                  <td style={{ padding: "4px 6px" }}>
                    <Typography variant="body2" fontWeight="bold">
                      {SLOT_NAMES[slot]}
                    </Typography>
                  </td>
                  {days.map((day) => {
                    const item = planMap[cellKey(day, slot)];
                    return (
                      <td key={day} style={{ padding: "3px 4px" }}>
                        <Button
                          fullWidth
                          size="small"
                          variant={item ? "outlined" : "text"}
                          color={active ? (slot === "comida" || slot === "cena" ? "primary" : "secondary") : "inherit"}
                          disabled={!active}
                          sx={{ minHeight: 44, textTransform: "none", opacity: active ? 1 : 0.4 }}
                          onClick={() => onAssign({ day, slot, current: item ?? null })}
                        >
                          {item ? (
                            <span>{item.recipe_name ?? item.free_text}</span>
                          ) : (
                            <span style={{ color: "text.disabled" }}>â€”</span>
                          )}
                        </Button>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </Box>
      <Typography variant="caption" color="text.secondary">
        {start} Â· Solo franjas activas (configÃºralas en Â«CategorÃ­asÂ»).
      </Typography>
    </Stack>
  );
}

function AssignDialog({
  day,
  slot,
  current,
  recipes,
  onClose,
  onSave,
  onClear,
}: {
  day: string;
  slot: string;
  current: MealPlanItem | null;
  recipes: RecipeBack[];
  onClose: () => void;
  onSave: (day: string, slot: string, payload: { recipe_id: number | null; free_text: string | null }) => void;
  onClear: (day: string, slot: string) => void;
}) {
  const compatible = useMemo(
    () => recipes.filter((r) => r.slots.includes(slot)).sort((a, b) => a.name.localeCompare(b.name)),
    [recipes, slot],
  );
  const [recipeId, setRecipeId] = useState<string>(current?.recipe_id ? String(current.recipe_id) : "");
  const [freeText, setFreeText] = useState(current?.free_text ?? "");

  const save = () => {
    const rid = recipeId ? Number(recipeId) : null;
    const text = freeText.trim() || null;
    if (!rid && !text) return;
    onSave(day, slot, { recipe_id: rid, free_text: text });
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>
        {SLOT_NAMES[slot]} Â· {weekdayOf(day)} {labelOf(day)}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <FormControl fullWidth size="small">
            <InputLabel id="assign-recipes-label">Receta</InputLabel>
            <Select
              labelId="assign-recipes-label"
              label="Receta"
              value={recipeId}
              onChange={(e: SelectChangeEvent) => setRecipeId(e.target.value)}
            >
              {compatible.map((r) => (
                <MenuItem key={r.id} value={r.id}>
                  {r.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            size="small"
            label="O texto libre"
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
          />
          {compatible.length === 0 && (
            <Alert severity="info">No hay recetas para esta franja: crea una en Â«RecetasÂ».</Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        {current && (
          <Button color="inherit" onClick={() => onClear(day, slot)}>
            Vaciar
          </Button>
        )}
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="contained" onClick={save} disabled={!recipeId && !freeText.trim()}>
          Guardar
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function RecipesTab({
  categories,
  recipes,
  onNew,
  onEdit,
  onDelete,
  onAddShopping,
}: {
  categories: Category[];
  recipes: RecipeBack[];
  onNew: () => void;
  onEdit: (r: RecipeBack) => void;
  onDelete: (id: number) => void;
  onAddShopping: (id: number) => void;
}) {
  const catName = useCallback(
    (id: number) => categories.find((c) => c.id === id)?.name ?? "â€”",
    [categories],
  );
  const byCat = useMemo(() => {
    const m: Record<number, RecipeBack[]> = {};
    for (const r of recipes) (m[r.category_id] ??= []).push(r);
    return m;
  }, [recipes]);
  return (
    <Stack spacing={2}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          Recetas ({recipes.length})
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={onNew}>
          Nueva receta
        </Button>
      </Stack>
      {recipes.length === 0 && (
        <Alert severity="info">AÃºn no tienes recetas. Crea la primera para usarlas en el plan.</Alert>
      )}
      {Object.entries(byCat).map(([catId, list]) => (
        <section key={catId}>
          <Typography variant="subtitle1" sx={{ mb: 1 }}>
            {catName(Number(catId))}
          </Typography>
          <Stack spacing={1}>
            {list.map((r) => (
              <Box key={r.id} sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.5 }}>
                <Stack direction="row" alignItems="center" spacing={1}>
                  <Typography sx={{ flexGrow: 1 }}>{r.name}</Typography>
                  <Stack direction="row" spacing={0.5}>
                    {r.slots.map((s) => (
                      <Chip key={s} label={SLOT_NAMES[s]} size="small" variant="outlined" />
                    ))}
                  </Stack>
                </Stack>
                {r.ingredients.length > 0 && (
                  <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
                    {r.ingredients.map((i) => `${i.name}${i.unit ? ` ${i.qty} ${i.unit}` : ""}`).join(" Â· ")}
                  </Typography>
                )}
                <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                  <Button size="small" variant="outlined" onClick={() => onAddShopping(r.id)}>
                    AÃ±adir a la compra
                  </Button>
                  <IconButton size="small" aria-label="editar receta" onClick={() => onEdit(r)}>
                    <EditIcon fontSize="small" />
                  </IconButton>
                  <IconButton size="small" aria-label="borrar receta" onClick={() => onDelete(r.id)}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Stack>
              </Box>
            ))}
          </Stack>
        </section>
      ))}
    </Stack>
  );
}

function CategoriesTab({
  slots,
  categories,
  goals,
  onToggleSlot,
  onNewCategory,
  newCat,
  setNewCat,
  onSaveGoal,
  onDeleteCategory,
}: {
  slots: SlotConfig[];
  categories: Category[];
  goals: Goal[];
  onToggleSlot: (s: SlotConfig) => void;
  onNewCategory: () => void;
  newCat: string;
  setNewCat: (v: string) => void;
  onSaveGoal: (g: Goal) => void;
  onDeleteCategory: (id: number) => void;
}) {
const [edits, setEdits] = useState<Record<number, { min: string; max: string }>>({});

  useEffect(() => {
    const initial: Record<number, { min: string; max: string }> = {};
    for (const g of goals) {
      initial[g.category_id] = { min: String(g.min_per_week), max: g.max_per_week === null ? "" : String(g.max_per_week) };
    }
    setEdits((prev) => (Object.keys(prev).length ? prev : initial));
  }, [goals]);

  return (
    <Stack spacing={3}>
      <section>
        <Typography variant="h6" sx={{ mb: 1 }}>
          Franjas activas
        </Typography>
        <Stack spacing={0}>
          {SLOT_ORDER.map((slot) => {
            const conf = slots.find((s) => s.slot === slot);
            if (!conf) return null;
            return (
              <FormControlLabel
                key={slot}
                control={<Switch checked={conf.enabled} onChange={() => onToggleSlot(conf)} />}
                label={SLOT_NAMES[slot]}
              />
            );
          })}
        </Stack>
      </section>

      <section>
        <Typography variant="h6" sx={{ mb: 1 }}>
          CategorÃ­as y objetivos semanales
        </Typography>
        <Stack spacing={1}>
          {goals.map((g) => {
            const edit = edits[g.category_id] ?? { min: String(g.min_per_week), max: g.max_per_week === null ? "" : String(g.max_per_week) };
            return (
              <Box key={g.category_id} sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.5 }}>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                  <Typography sx={{ flexGrow: 1 }}>{g.name}</Typography>
                  {g.is_default && (
                    <Chip label="objetivo por defecto" size="small" variant="outlined" color="default" />
                  )}
                  {categories.find((c) => c.id === g.category_id && c.user_id !== null) && (
                    <IconButton size="small" aria-label="borrar categorÃ­a" onClick={() => onDeleteCategory(g.category_id)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  )}
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <TextField
                    size="small"
                    label="MÃ­nimo/semana"
                    type="number"
                    inputProps={{ min: 0, max: 30 }}
                    value={edit.min}
                    onChange={(e) => setEdits((m) => ({ ...m, [g.category_id]: { ...m[g.category_id] ?? edit, min: e.target.value } }))}
                    sx={{ width: 130 }}
                  />
                  <TextField
                    size="small"
                    label="MÃ¡ximo/semana"
                    type="number"
                    inputProps={{ min: 0, max: 30 }}
                    value={edit.max}
                    onChange={(e) => setEdits((m) => ({ ...m, [g.category_id]: { ...m[g.category_id] ?? edit, max: e.target.value } }))}
                    sx={{ width: 130 }}
                  />
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() =>
                      onSaveGoal({
                        category_id: g.category_id,
                        name: g.name,
                        min_per_week: Math.max(0, Number(edit.min) || 0),
                        max_per_week: edit.max === "" ? null : Math.max(0, Number(edit.max) || 0),
                        is_default: false,
                      })
                    }
                  >
                    Guardar
                  </Button>
                </Stack>
              </Box>
            );
          })}
        </Stack>
      </section>

      <section>
        <Typography variant="h6" sx={{ mb: 1 }}>
          Nueva categorÃ­a
        </Typography>
        <Stack direction="row" spacing={1}>
          <TextField
            size="small"
            placeholder="Ej.: postres"
            value={newCat}
            onChange={(e) => setNewCat(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onNewCategory();
            }}
            sx={{ flexGrow: 1 }}
          />
          <Button variant="contained" onClick={onNewCategory} disabled={!newCat.trim()}>
            Crear
          </Button>
        </Stack>
      </section>
    </Stack>
  );
}

function RecipeDialog({
  RecipeBack,
  categories,
  onClose,
  onSaved,
}: {
  RecipeBack: RecipeBack | null;
  categories: Category[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(RecipeBack?.name ?? "");
  const [categoryId, setCategoryId] = useState<string>(RecipeBack ? String(RecipeBack.category_id) : "");
  const [slots, setSlots] = useState<string[]>(RecipeBack?.slots ?? []);
  const [notes, setNotes] = useState(RecipeBack?.notes ?? "");
  const [ingredients, setIngredients] = useState<{ rowKey: number; name: string; qty: string; unit: string }[]>(
    () =>
      RecipeBack?.ingredients.map((i) => ({
        rowKey: i.sort_order,
        name: i.name,
        qty: String(i.qty),
        unit: i.unit ?? "",
      })) ?? [],
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleSlot = (s: string) =>
    setSlots((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));

  const save = async () => {
    if (!name.trim() || !categoryId) return;
    setSaving(true);
    setError(null);
    const payload = {
      name: name.trim(),
      category_id: Number(categoryId),
      slots,
      notes: notes.trim() || null,
      ingredients: ingredients
        .filter((i) => i.name.trim())
        .map((i) => ({ name: i.name.trim(), qty: Number(i.qty) || 0, unit: i.unit.trim() || null })),
    };
    try {
      if (RecipeBack) await menuApi.updateRecipe(RecipeBack.id, payload);
      else await menuApi.createRecipe(payload);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{RecipeBack ? "Editar receta" : "Nueva receta"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            size="small"
            label="Nombre"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <FormControl fullWidth size="small">
            <InputLabel id="RecipeBack-category-label">CategorÃ­a</InputLabel>
            <Select
              labelId="RecipeBack-category-label"
              label="CategorÃ­a"
              value={categoryId}
              onChange={(e: SelectChangeEvent) => setCategoryId(e.target.value)}
            >
              {categories.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  {c.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Box>
            <Typography variant="body2" sx={{ mb: 0.5 }}>
              Franjas aptas
            </Typography>
            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
              {SLOT_ORDER.map((s) => (
                <Chip
                  key={s}
                  label={SLOT_NAMES[s]}
                  color={slots.includes(s) ? "primary" : "default"}
                  onClick={() => toggleSlot(s)}
                />
              ))}
            </Stack>
          </Box>
          <TextField
            size="small"
            label="Notas"
            multiline
            minRows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <Box>
            <Typography variant="body2" sx={{ mb: 0.5 }}>
              Ingredientes (se suman si comparten nombre)
            </Typography>
            <Stack spacing={1}>
              {ingredients.map((row) => (
                <Stack key={row.rowKey} direction="row" spacing={1} alignItems="center">
                  <TextField
                    size="small"
                    placeholder="Ingrediente"
                    value={row.name}
                    onChange={(e) =>
                      setIngredients((cur) => cur.map((r) => (r.rowKey === row.rowKey ? { ...r, name: e.target.value } : r)))
                    }
                    sx={{ flexGrow: 1 }}
                  />
                  <TextField
                    size="small"
                    placeholder="Cantidad"
                    type="number"
                    value={row.qty}
                    onChange={(e) =>
                      setIngredients((cur) => cur.map((r) => (r.rowKey === row.rowKey ? { ...r, qty: e.target.value } : r)))
                    }
                    sx={{ width: 90 }}
                  />
                  <TextField
                    size="small"
                    placeholder="Unidad"
                    value={row.unit}
                    onChange={(e) =>
                      setIngredients((cur) => cur.map((r) => (r.rowKey === row.rowKey ? { ...r, unit: e.target.value } : r)))
                    }
                    sx={{ width: 90 }}
                  />
                  <IconButton
                    size="small"
                    aria-label="quitar ingrediente"
                    onClick={() => setIngredients((cur) => cur.filter((r) => r.rowKey !== row.rowKey))}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Stack>
              ))}
              <Button
                size="small"
                startIcon={<AddIcon />}
                onClick={() =>
                  setIngredients((cur) => [...cur, { rowKey: Date.now(), name: "", qty: "", unit: "" }])
                }
              >
                AÃ±adir ingrediente
              </Button>
            </Stack>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancelar</Button>
        <Button variant="contained" onClick={() => void save()} disabled={saving || !name.trim() || !categoryId}>
          Guardar
        </Button>
      </DialogActions>
    </Dialog>
  );
}

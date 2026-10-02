export interface User {
  id: number;
  email: string | null;
  profile_type: string;
  display_name: string | null;
  course: string | null;
  timezone: string;
  notification_tone: string;
  tone_source: string;
  /** Adulto que creó la cuenta. `null` en las cuentas antiguas y en el adulto. */
  parent_id: number | null;
  /** Tope de minutos de estudio al día. 0 = sin tope. */
  study_max_minutes: number;
  age: number | null;
  created_at: string;
}

export interface AuthResponse {
  token: string;
  user: User;
}

const TOKEN_KEY = "loopy_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* cuerpo no JSON */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  /** Alta de cuenta adulta. Las de niño las crea un adulto en `createChild`. */
  register: (payload: { email: string; password: string; timezone: string }) =>
    request<AuthResponse>("/api/auth/register", { method: "POST", body: JSON.stringify(payload) }),
  login: (payload: { email: string; password: string }) =>
    request<AuthResponse>("/api/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  /** Entrada de los menores: nombre + PIN, sin email. */
  childLogin: (payload: { display_name: string; pin: string }) =>
    request<AuthResponse>("/api/auth/child-login", { method: "POST", body: JSON.stringify(payload) }),
  /** El adulto da de alta la cuenta del niño. El PIN no se puede recuperar después. */
  createChild: (payload: {
    display_name: string;
    pin: string;
    birth_date: string;
    course?: string | null;
  }) => request<User>("/api/auth/children", { method: "POST", body: JSON.stringify(payload) }),
  children: () => request<User[]>("/api/auth/children"),
  me: () => request<User>("/api/auth/me"),
  updateMe: (payload: {
    display_name?: string | null;
    course?: string | null;
    study_max_minutes?: number | null;
  }) => request<User>("/api/auth/me", { method: "PATCH", body: JSON.stringify(payload) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  requestPasswordReset: (payload: { email: string }) =>
    request<{ detail: string }>("/api/auth/password-reset/request", { method: "POST", body: JSON.stringify(payload) }),
  confirmPasswordReset: (payload: { token: string; new_password: string }) =>
    request<{ detail: string }>("/api/auth/password-reset/confirm", { method: "POST", body: JSON.stringify(payload) }),
};

export interface Task {
  id: number;
  category: string;
  title: string;
  notes: string | null;
  room_id: number | null;
  subject_id: number | null;
  due_on: string | null;
  due_at: string | null;
  notify: boolean;
  rec_type: string | null;
  rec_interval: number;
  rec_unit: string | null;
  rec_week_mask: number;
  rec_day_of_month: number | null;
  rec_anchor: string | null;
  rec_next_due: string | null;
  rotation_group_id: number | null;
  rotation_index: number | null;
  pending_from_class: boolean;
  est_minutes: number | null;
  done_minutes: number;
  last_done_on: string | null;
  archived_at: string | null;
  sort: number;
  created_at: string;
  pending: string | null;
  done: string[];
}

export type TaskCategory = "general" | "hogar" | "colegio-deberes" | "colegio-trabajo" | "puntual";

export const taskApi = {
  list: (date?: string, category?: string) => {
    const params = new URLSearchParams();
    if (date) params.set("date", date);
    if (category) params.set("category", category);
    const qs = params.toString();
    return request<Task[]>(`/api/tasks${qs ? `?${qs}` : ""}`);
  },
  create: (payload: Partial<Task> & { title: string; category: string }) =>
    request<Task>("/api/tasks", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: number, payload: Partial<Task>) =>
    request<Task>(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  remove: (id: number) => request<void>(`/api/tasks/${id}`, { method: "DELETE" }),
  complete: (id: number, done_on: string) =>
    request<{ id: number; done_on: string; rec_next_due: string | null }>(`/api/tasks/${id}/complete`, {
      method: "POST",
      body: JSON.stringify({ done_on }),
    }),
  undo: (id: number, done_on: string) => request<void>(`/api/tasks/${id}/complete/${done_on}`, { method: "DELETE" }),
  advance: (id: number) =>
    request<{ id: number; done_on: string; rec_next_due: string | null }>(`/api/tasks/${id}/advance`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
};

// ---------------------------------------------------------------- pendientes (paso 7)

export interface PendingList {
  overdue: Task[];
  today: Task[];
}

export interface BulkError {
  task_id: number;
  detail: string;
}

export interface BulkCompleteResult {
  completed: number[];
  errors: BulkError[];
  done_on: string;
}

export const pendingApi = {
  list: () => request<PendingList>("/api/pending"),
  complete: (task_ids: number[]) =>
    request<BulkCompleteResult>("/api/pending/complete", { method: "POST", body: JSON.stringify({ task_ids }) }),
};

export interface Room {
  id: number;
  name: string;
  sort_order: number;
  color: string | null;
}

export const roomApi = {
  list: () => request<Room[]>("/api/rooms"),
  create: (payload: { name: string; color?: string | null }) =>
    request<Room>("/api/rooms", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: number, payload: Partial<Room>) =>
    request<Room>(`/api/rooms/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  remove: (id: number) => request<void>(`/api/rooms/${id}`, { method: "DELETE" }),
};

// ---------------------------------------------------------------- hogar (adulto)

export interface HomeItem {
  id: number;
  category: string;
  title: string;
  notes: string | null;
  room_id: number | null;
  due_on: string | null;
  due_at: string | null;
  notify: boolean;
  rec_type: string | null;
  est_minutes: number | null;
  last_done_on: string | null;
  sort: number;
  created_at: string;
  pending: string | null;
  next_on: string | null;
  done: string[];
}

export interface HomeGroup {
  pending: HomeItem[];
  ahead: HomeItem[];
}

export interface HomeRoom {
  id: number;
  name: string;
  color: string | null;
  pending: HomeItem[];
  ahead: HomeItem[];
}

export interface HomeOut {
  day: string;
  rooms: HomeRoom[];
  no_room: HomeGroup;
}

export const homeApi = {
  get: (day?: string) => {
    const qs = day ? `?day=${day}` : "";
    return request<HomeOut>(`/api/home${qs}`);
  },
};

// ---------------------------------------------------------------- compra

export interface ShoppingItem {
  id: number;
  name: string;
  qty: string | null;
  added_at: string;
  purchased: boolean;
  purchased_at: string | null;
  source: string;
  source_ref: string | null;
}

export interface ShoppingRecommend {
  name: string;
  qty: string | null;
  count: number;
}

export const shoppingApi = {
  list: () => request<ShoppingItem[]>("/api/shopping"),
  create: (payload: { name: string; qty?: string | null }) =>
    request<ShoppingItem>("/api/shopping", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: number, payload: Partial<ShoppingItem>) =>
    request<ShoppingItem>(`/api/shopping/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  purchase: (id: number) => request<ShoppingItem>(`/api/shopping/${id}/purchase`, { method: "POST" }),
  unpurchase: (id: number) => request<ShoppingItem>(`/api/shopping/${id}/unpurchase`, { method: "POST" }),
  remove: (id: number) => request<void>(`/api/shopping/${id}`, { method: "DELETE" }),
  recommend: () => request<ShoppingRecommend[]>("/api/shopping/recommend"),
};

// ---------------------------------------------------------------- resumen diario

export interface SummaryConfig {
  enabled: boolean;
  time: string;
  week_mask: number;
}

export interface SummaryException {
  date: string;
  action: "skip" | "add";
}

export const summaryApi = {
  config: () => request<SummaryConfig>("/api/summary/config"),
  patchConfig: (payload: Partial<SummaryConfig>) =>
    request<SummaryConfig>("/api/summary/config", { method: "PATCH", body: JSON.stringify(payload) }),
  month: (month: string) => request<{ month: string; days: SummaryException[] }>(`/api/summary?month=${month}`),
  putException: (day: string, action: "skip" | "add") =>
    request<SummaryException>(`/api/summary/exceptions/${day}`, { method: "PUT", body: JSON.stringify({ action }) }),
  deleteException: (day: string) => request<void>(`/api/summary/exceptions/${day}`, { method: "DELETE" }),
};

// ---------------------------------------------------------------- check-in

// ---------------------------------------------------------------- colegio

export interface Subject {
  id: number;
  name: string;
  color: string | null;
  prep_minutes: number;
  session_minutes: number;
  days_resumen: number;
  days_estudio: number;
  days_practica: number;
  days_repaso: number;
  include_weekends: boolean;
  resumen_total_pages: number | null;
  resumen_done_pages: number;
}

/** Al crear, el tiempo y el reparto son opcionales: la API pone los de por defecto. */
export type SubjectCreate = Partial<
  Omit<Subject, "id" | "resumen_done_pages" | "prep_minutes" | "session_minutes">
> &
  Pick<Subject, "name"> & {
    prep_minutes?: number;
    session_minutes?: number;
  };

export interface Exam {
  id: number;
  subject_id: number;
  subject_name: string | null;
  exam_date: string;
  notes: string | null;
  prep_minutes_override: number | null;
  created_at: string;
}

export type PlanPhase = "repaso-final" | "repaso" | "practica" | "estudio" | "resumen";

export interface PlanItem {
  date: string;
  phase: PlanPhase;
  offset: number;
  status: "done" | "skip" | null;
  done_at: string | null;
  label: string | null;
  minutes: number;
}

/** El plan en minutos y sesiones, para poder decirlo sin jerga. */
export interface PlanProgress {
  session_minutes: number;
  prep_minutes: number;
  total_sessions: number;
  total_minutes: number;
  done_sessions: number;
  pending_sessions: number;
  pending_minutes: number;
}

export interface ExamPlan {
  exam: Exam;
  subject: {
    id: number;
    name: string;
    color: string | null;
    prep_minutes: number;
    session_minutes: number;
  };
  items: PlanItem[];
  resumen_done_pages: number;
  resumen_total_pages: number | null;
  resumen_omitted: boolean;
  resumen_partial: boolean;
  progress: PlanProgress;
}

export interface Extracurricular {
  id: number;
  name: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
  start_on: string | null;
  end_on: string | null;
}

export interface WorkSession {
  id: number;
  kind: string;
  task_id: number | null;
  planned_seconds: number;
  actual_seconds: number;
  completed_at: string | null;
  created_at: string;
}

export const subjectApi = {
  list: () => request<Subject[]>("/api/subjects"),
  create: (payload: SubjectCreate) =>
    request<Subject>("/api/subjects", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: number, payload: Partial<Subject>) =>
    request<Subject>(`/api/subjects/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  remove: (id: number) => request<void>(`/api/subjects/${id}`, { method: "DELETE" }),
  advanceResumen: (id: number, date?: string) =>
    request<PlanItem>(`/api/subjects/${id}/resumen/advance`, {
      method: "POST",
      body: JSON.stringify(date ? { date } : {}),
    }),
  undoAdvanceResumen: (id: number, date: string) =>
    request<{ removed: boolean }>(`/api/subjects/${id}/resumen/advance/${date}`, { method: "DELETE" }),
  addSession: (id: number, payload?: SubjectSessionInput) =>
    request<PlanItem>(`/api/subjects/${id}/sessions`, { method: "POST", body: JSON.stringify(payload ?? {}) }),
  undoSession: (id: number, date: string, phase?: PlanPhase) => {
    const qs = phase ? `?phase=${phase}` : "";
    return request<{ removed: boolean }>(`/api/subjects/${id}/sessions/${date}${qs}`, { method: "DELETE" });
  },
};

export const examApi = {
  list: () => request<Exam[]>("/api/exams"),
  create: (payload: { subject_id: number; exam_date: string; notes?: string | null; prep_minutes_override?: number | null }) =>
    request<Exam>("/api/exams", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: number, payload: Partial<Exam>) =>
    request<Exam>(`/api/exams/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  remove: (id: number) => request<void>(`/api/exams/${id}`, { method: "DELETE" }),
  plan: (id: number, from?: string, to?: string) => {
    const params = new URLSearchParams();
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    const qs = params.toString();
    return request<ExamPlan>(`/api/exams/${id}/plan${qs ? `?${qs}` : ""}`);
  },
  markPlanItem: (id: number, date: string, status: "done" | "skip") =>
    request<{ removed: boolean }>(`/api/exams/${id}/plan/${date}`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  undoPlanItem: (id: number, date: string) =>
    request<{ removed: boolean }>(`/api/exams/${id}/plan/${date}`, { method: "DELETE" }),
};

export interface CalendarTask {
  id: number;
  title: string;
  category: string;
  subject_id: number | null;
  due_on: string | null;
  done: boolean;
}

export interface CalendarPlan {
  exam_id: number | null;
  subject_id: number;
  subject_name: string | null;
  subject_color: string | null;
  phase: PlanPhase;
  date: string;
  offset: number;
  status: "done" | "skip" | null;
  done_at: string | null;
  label: string | null;
  session: boolean;
}

export interface CalendarDay {
  tasks: CalendarTask[];
  plan: CalendarPlan[];
}

export interface Calendar {
  from: string;
  to: string;
  days: Record<string, CalendarDay>;
  /** Minutos de estudio que no caben bajo el tope diario en el rango pedido. */
  unplaced_study_minutes: number;
  /** El tope con el que se repartió el plan. 0 = sin tope. */
  daily_max_minutes: number;
}

export const calendarApi = {
  get: (from: string, to: string) => {
    const qs = new URLSearchParams({ from, to });
    return request<Calendar>(`/api/calendar?${qs.toString()}`);
  },
};

/** Minutos que ocupa un día y si el plan de estudio cabe en el tope. */
export interface DayLoad {
  date: string;
  /** Tope de estudio diario. 0 = sin tope. */
  daily_max_minutes: number;
  study_minutes: number;
  study_done_minutes: number;
  task_minutes: number;
  tasks_pending: number;
  /** Tareas sin `est_minutes` y sin historial: no se les inventa duración. */
  tasks_without_estimate: number;
  blocked_minutes: number;
  total_minutes: number;
  over_cap_minutes: number;
  unplaced_study_minutes: number;
  exams_pending: number;
}

export const dayLoadApi = {
  get: (date?: string) => {
    const qs = date ? `?date=${date}` : "";
    return request<DayLoad>(`/api/day-load${qs}`);
  },
};

export interface SubjectSessionInput {
  date?: string;
  phase?: PlanPhase;
}

export const extracurricularApi = {
  list: () => request<Extracurricular[]>("/api/extracurriculars"),
  create: (payload: Omit<Extracurricular, "id">) =>
    request<Extracurricular>("/api/extracurriculars", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: number, payload: Partial<Extracurricular>) =>
    request<Extracurricular>(`/api/extracurriculars/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  remove: (id: number) => request<void>(`/api/extracurriculars/${id}`, { method: "DELETE" }),
};

export interface WorkSessionEstimate {
  suggested_minutes: number | null;
  samples: number;
  based_on: string;
  planned_minutes: number;
  actual_minutes: number;
}

export const workSessionApi = {
  create: (payload: Omit<WorkSession, "id" | "created_at">) =>
    request<WorkSession>("/api/work-sessions", { method: "POST", body: JSON.stringify(payload) }),
  list: () => request<WorkSession[]>("/api/work-sessions"),
  estimate: (params: { kind: string; task_id?: number; planned_minutes?: number }) => {
    const q = new URLSearchParams({ kind: params.kind });
    if (params.task_id !== undefined) q.set("task_id", String(params.task_id));
    if (params.planned_minutes !== undefined) q.set("planned_minutes", String(params.planned_minutes));
    return request<WorkSessionEstimate>(`/api/work-sessions/estimate?${q.toString()}`);
  },
};

// ---------------------------------------------------------------- check-in

export interface CheckinConfig {
  enabled: boolean;
  time: string;
  week_mask: number;
}

export interface CheckinTone {
  notification_tone: string;
  template: string;
}

export type QuickItemType = "deber" | "examen" | "proyecto";

export interface QuickItem {
  type: QuickItemType;
  title?: string | null;
  subject_id?: number | null;
  exam_date?: string | null;
  est_minutes?: number | null;
  pending_from_class?: boolean;
  due_on?: string | null;
  notes?: string | null;
}

export interface QuickAddResult {
  day: string;
  deberes: {
    id: number;
    kind: "deber";
    title: string;
    subject_id: number | null;
    due_on: string | null;
    est_minutes: number | null;
    pending_from_class: boolean;
  }[];
  proyectos: {
    id: number;
    kind: "proyecto";
    title: string;
    subject_id: number | null;
    due_on: string | null;
    est_minutes: number | null;
  }[];
  examenes: {
    id: number;
    kind: "examen";
    subject_id: number;
    subject_name: string | null;
    exam_date: string;
    notes: string | null;
  }[];
}

export const checkinApi = {
  config: () => request<CheckinConfig>("/api/checkin/config"),
  patchConfig: (payload: Partial<CheckinConfig>) =>
    request<CheckinConfig>("/api/checkin/config", { method: "PATCH", body: JSON.stringify(payload) }),
  tone: () => request<CheckinTone>("/api/checkin/tone"),
  addItems: (items: QuickItem[], day?: string) =>
    request<QuickAddResult>("/api/checkin/items", {
      method: "POST",
      body: JSON.stringify({ day, items }),
    }),
};

// ---------------------------------------------------------------- push

export interface PushConfig {
  enabled: boolean;
  public_key: string;
  segment: string | null;
}

function subToPayload(sub: PushSubscription): { endpoint: string; p256dh: string; auth: string } {
  const toB64 = (key: ArrayBuffer | null): string => {
    if (!key) return "";
    const bytes = new Uint8Array(key);
    let bin = "";
    for (const b of bytes) bin += String.fromCharCode(b);
    return btoa(bin);
  };
  return {
    endpoint: sub.endpoint,
    p256dh: toB64(sub.getKey("p256dh")),
    auth: toB64(sub.getKey("auth")),
  };
}

export function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

// ---------------------------------------------------------------- menú de comidas (paso 8)

export interface SlotConfig {
  slot: string;
  enabled: boolean;
  default_time: string | null;
}

export interface Category {
  id: number;
  name: string;
  user_id: number | null;
  order: number;
}

export interface Goal {
  category_id: number;
  name: string;
  min_per_week: number;
  max_per_week: number | null;
  is_default: boolean;
}

export interface RecipeIngredient {
  id: number;
  name: string;
  qty: number;
  unit: string | null;
  sort_order: number;
}

export interface RecipeBack {
  id: number;
  name: string;
  category_id: number;
  slots: string[];
  notes: string | null;
  ingredients: RecipeIngredient[];
}

export interface RecipeUpsert {
  name: string;
  category_id: number;
  slots: string[];
  notes: string | null;
  ingredients: { name: string; qty: number; unit: string | null }[];
}

export interface MealPlanItem {
  date: string;
  slot: string;
  recipe_id: number | null;
  recipe_name: string | null;
  free_text: string | null;
}

export interface WeekPlan {
  start: string;
  plans: MealPlanItem[];
}

export interface AddToShoppingResult {
  created: number;
  updated: number;
}

export interface RecommendResult {
  filled: number;
  plans: MealPlanItem[];
}

export const menuApi = {
  slots: () => request<{ slots: SlotConfig[] }>("/api/menu/slots"),
  patchSlot: (slot: string, payload: Partial<SlotConfig>) =>
    request<SlotConfig>(`/api/menu/slots/${slot}`, { method: "PATCH", body: JSON.stringify(payload) }),
  categories: () => request<Category[]>("/api/menu/categories"),
  createCategory: (name: string) =>
    request<Category>("/api/menu/categories", { method: "POST", body: JSON.stringify({ name }) }),
  removeCategory: (id: number) => request<void>(`/api/menu/categories/${id}`, { method: "DELETE" }),
  goals: () => request<Goal[]>("/api/menu/goals"),
  patchGoal: (categoryId: number, payload: { min_per_week: number; max_per_week: number | null }) =>
    request<Goal>(`/api/menu/goals/${categoryId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  recipes: (categoryId?: number) => {
    const qs = categoryId ? `?category_id=${categoryId}` : "";
    return request<RecipeBack[]>(`/api/menu/recipes${qs}`);
  },
  createRecipe: (payload: RecipeUpsert) =>
    request<RecipeBack>("/api/menu/recipes", { method: "POST", body: JSON.stringify(payload) }),
  updateRecipe: (id: number, payload: Partial<RecipeUpsert>) =>
    request<RecipeBack>(`/api/menu/recipes/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  removeRecipe: (id: number) => request<void>(`/api/menu/recipes/${id}`, { method: "DELETE" }),
  plan: (start: string) => request<WeekPlan>(`/api/menu/plan?start=${start}`),
  setPlan: (day: string, slot: string, payload: { recipe_id: number | null; free_text: string | null }) =>
    request<MealPlanItem>(`/api/menu/plan/${day}/${slot}`, { method: "PUT", body: JSON.stringify(payload) }),
  clearPlan: (day: string, slot: string) => request<void>(`/api/menu/plan/${day}/${slot}`, { method: "DELETE" }),
  copyWeek: (from_date: string, to_date: string) =>
    request<{ copied: number }>("/api/menu/plan/copy", { method: "POST", body: JSON.stringify({ from_date, to_date }) }),
  recommend: (start: string) =>
    request<RecommendResult>("/api/menu/plan/recommend", { method: "POST", body: JSON.stringify({ start }) }),
  addRecipeToShopping: (recipe_id: number) =>
    request<AddToShoppingResult>("/api/menu/shopping", { method: "POST", body: JSON.stringify({ recipe_id }) }),
  addWeekToShopping: (start: string) =>
    request<AddToShoppingResult>("/api/menu/shopping", { method: "POST", body: JSON.stringify({ start }) }),
};

export const pushApi = {
  config: () => request<PushConfig>("/api/push/config"),
  subscribe: (sub: PushSubscription) =>
    request<{ subscribed: boolean }>("/api/push/subscribe", {
      method: "POST",
      body: JSON.stringify({ ...subToPayload(sub), user_agent: navigator.userAgent }),
    }),
  unsubscribe: (sub: PushSubscription) =>
    request<void>("/api/push/subscribe", { method: "DELETE", body: JSON.stringify(subToPayload(sub)) }),
  test: () => request<{ queued: boolean }>("/api/push/test", { method: "POST" }),
};
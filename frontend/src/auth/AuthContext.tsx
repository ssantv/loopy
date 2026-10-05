import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import {
  api,
  ApiError,
  OfflineError,
  getToken,
  setToken,
  clearToken,
  cachedUser,
  rememberUser,
  type User,
} from "../api/client";
import { CACHE_LECTURAS } from "../offline";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  /** Entrada del menor con su nombre y su PIN. */
  loginChild: (displayName: string, pin: string) => Promise<void>;
  register: (payload: {
    email: string;
    password: string;
    timezone: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then((u) => {
        setUser(u);
        // Solo cuando el servidor ha contestado. La copia cacheada nunca se refresca
        // "a ojo", para que abrir la app sin red no enseñe un usuario inventado.
        rememberUser(u);
      })
      .catch((e: unknown) => {
        // Aquí estaba el bug más caro de la app: `.catch(() => clearToken())` se
        // llevaba el token con cualquier fallo, y un fallo de red no significa que la
        // sesión haya caducado. Abrir la app en el metro cerraba la sesión de verdad, y
        // luego ni se podía volver a entrar porque tampoco hay red.
        if (e instanceof OfflineError) {
          const u = cachedUser();
          if (u) {
            setUser(u);
            return;
          }
          // No hay copia cacheada del usuario, pero el token sí. Lo más seguro es
          // conservar el token: si vuelve la red lo comprobará, y no se desconecta
          // al usuario justo en el momento en que no hay red.
          setUser(null);
          return;
        }
        if (e instanceof ApiError && e.status === 401) {
          // Aquí sí: el servidor ha dicho que el token no vale.
          clearToken();
          setUser(null);
          return;
        }
        // Cualquier otra cosa (500, un cuerpo raro) no debe cerrar la sesión. Se deja el
        // token donde está y se sale a la pantalla de inicio, que será la que avise.
        setUser(cachedUser());
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (email: string, password: string) => {
    const res = await api.login({ email, password });
    setToken(res.token);
    setUser(res.user);
    // También al entrar, no solo al arrancar. Si no, entrar y perder la señal a los
    // cinco minutos deja la app sin copia del usuario, y al volver a abrir sin red
    // manda a `/login`, que es justo el fallo que se quería arreglar.
    rememberUser(res.user);
  };

  const loginChild = async (displayName: string, pin: string) => {
    const res = await api.childLogin({ display_name: displayName, pin });
    setToken(res.token);
    setUser(res.user);
    rememberUser(res.user);
  };

  const register = async (payload: { email: string; password: string; timezone: string }) => {
    const res = await api.register(payload);
    setToken(res.token);
    setUser(res.user);
    rememberUser(res.user);
  };

  const logout = async () => {
    try {
      await api.logout();
    } finally {
      clearToken();
      setUser(null);
      // Las lecturas cacheadas son de la familia que acaba de salir, y en un tablet
      // compartido la siguiente persona que abra la app sin red las vería: nombres,
      // tareas y notas de otro. Es la misma razón por la que se borra el token.
      // `caches` no existe en algunos navegadores antiguos y el cierre de sesión no
      // puede fallar por eso.
      if ("caches" in window) await caches.delete(CACHE_LECTURAS).catch(() => {});
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, loginChild, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de AuthProvider");
  return ctx;
}
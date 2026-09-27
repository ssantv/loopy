// QA del flujo de reset de contraseña, de punta a punta contra la API real.
//  1. Login muestra el enlace "olvidé mi contraseña".
//  2. Pedir el reset siempre responde lo mismo (no filtra si el email existe).
//  3. Confirmar con el token real cambia la contraseña.
//  4. La contraseña vieja deja de servir y la nueva sí.
//  5. Sin token, la pantalla avisa en vez de mostrar un formulario inútil.
const EMAIL = 'reset.e2e@test.com'
const VIEJA = 'viejaClave123'
const NUEVA = 'nuevaClave456'

const api = (path, body, method = 'POST') =>
  fetch(`http://127.0.0.1:8000${path}`, {
    method,
    headers: { 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })

export default async function run(page, ui) {
  const out = { pasos: [] }

  // --- 1. Login: existe el enlace al reset ---
  await page.goto('http://localhost:5173/login')
  await page.waitForSelector('input[type=email]')
  out.pasos.push({ paso: 'login', hayEnlaceReset: (await page.getByText(/olvid/i).first().count()) > 0 })

  // --- 2. Registrar la cuenta ---
  const reg = await api('/api/auth/register', {
    email: EMAIL,
    password: VIEJA,
    profile_type: 'adult',
  })
  out.pasos.push({ paso: 'registro', status: reg.status })

  // Token本の Confirm necesita un token vivo. Si lo pasamos por entorno, NO pedimos
  // otro reset para esta cuenta: pedirlo invalidaría los tokens anteriores.
  const token = process.env.RESET_TOKEN || ''
  if (!token) {
    const pedir = await api('/api/auth/password-reset/request', { email: EMAIL })
    out.pasos.push({ paso: 'pedir-reset', status: pedir.status, mensaje: (await pedir.json()).detail })
  } else {
    out.pasos.push({ paso: 'pedir-reset', saltado: 'se usa el token de entorno' })
  }

  // Email inexistente -> mismo status y mismo texto (no enumera cuentas).
  const pedirFantasma = await api('/api/auth/password-reset/request', { email: 'nadie.de.este.test@test.com' })
  const fantasmaJson = await pedirFantasma.json()
  out.noEnumeraCuentas = pedirFantasma.status === 202 && /si el email existe/i.test(fantasmaJson.detail)

  // --- 3. Confirmar el reset con el token ---
  if (!token) {
    out.pasos.push({ paso: 'confirmar', saltado: 'falta RESET_TOKEN (ver docs/qa-reset-password.mjs)' })
    return out
  }
  const confirmar = await api('/api/auth/password-reset/confirm', { token, new_password: NUEVA })
  out.pasos.push({ paso: 'confirmar', status: confirmar.status, mensaje: (await confirmar.json()).detail })

  // --- 4. Reusar el token debe fallar (un solo uso) ---
  const reuso = await api('/api/auth/password-reset/confirm', { token, new_password: 'otraClave999' })
  out.pasos.push({ paso: 'reusar-token', status: reuso.status })

  // --- 5. La contraseña nueva sirve, la vieja no ---
  const loginViejo = await api('/api/auth/login', { email: EMAIL, password: VIEJA })
  const loginNuevo = await api('/api/auth/login', { email: EMAIL, password: NUEVA })
  out.pasos.push({ paso: 'login-viejo', status: loginViejo.status })
  out.pasos.push({ paso: 'login-nuevo', status: loginNuevo.status })

  // --- 6. La UI del reset con token ---
  await page.goto(`http://localhost:5173/reset-password?token=${encodeURIComponent(token)}`)
  await page.waitForTimeout(800)
  out.pasos.push({ paso: 'ui-reset-con-token', url: new URL(page.url()).pathname })

  // --- 7. La UI sin token avisa, no muestra formulario ---
  await page.goto('http://localhost:5173/reset-password')
  await page.waitForTimeout(800)
  out.pasos.push({
    paso: 'ui-reset-sin-token',
    avisa: !!(await page.getByText(/no es v/i).first().count()),
    tieneFormulario: !!(await page.locator('input[type=password]').count()),
  })

  return out
}

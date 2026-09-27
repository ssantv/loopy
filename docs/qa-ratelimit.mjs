// QA del rate limit del login: 5 intentos fallidos -> el bloqueo debe verse en la UI.
// Espera a que el texto del Alert CAMBIE en cada intento (si no, lee el aviso viejo).
const EMAIL = 'prueba@prueba.es'
const PASSWORD = '12345678'
const MAX = 6

const alertText = (page) =>
  page
    .locator('.MuiAlert-root')
    .first()
    .textContent({ timeout: 1500 })
    .then((t) => (t || '').replace(/\s+/g, ' ').trim())
    .catch(() => '')

export default async function run(page, ui) {
  await page.goto('http://localhost:5173/login')
  await page.waitForSelector('input[type=email]')

  const intentos = []
  let visto = ''

  for (let i = 1; i <= MAX; i++) {
    await page.fill('input[type=email]', EMAIL)
    await page.fill('input[type=password]', 'incorrecta')
    await page.getByRole('button', { name: 'ENTRAR' }).click()
    // Espera a que el alert pase del texto anterior a uno nuevo.
    await page
      .waitForFunction(
        (prev) => {
          const el = document.querySelector('.MuiAlert-root')
          const txt = el ? el.textContent.replace(/\s+/g, ' ').trim() : ''
          return txt !== prev || location.pathname !== '/login'
        },
        visto,
        { timeout: 10000 },
      )
      .catch(() => {})
    const actual = await alertText(page)
    visto = actual
    intentos.push({ intento: i, alert: actual, url: new URL(page.url()).pathname })
    if (new URL(page.url()).pathname !== '/login') break
  }

  // Con la cuenta bloqueada, la contraseÃ±a correcta tampoco debe dejar entrar.
  await page.fill('input[type=email]', EMAIL)
  await page.fill('input[type=password]', PASSWORD)
  await page.getByRole('button', { name: 'ENTRAR' }).click()
  await page
    .waitForFunction(() => !!document.querySelector('.MuiAlert-root') || location.pathname !== '/login', null, {
      timeout: 10000,
    })
    .catch(() => {})
  const conPasswdOk = (await alertText(page)) || '(sin alert)'

  return {
    intentos,
    rutaFinal: new URL(page.url()).pathname,
    entroConPasswdCorrecta: new URL(page.url()).pathname !== '/login',
    mensajeConPasswdCorrecta: conPasswdOk,
  }
}

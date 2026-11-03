import {
  clearSession,
  defineEventHandler,
  getMethod,
  getRequestHeader,
  sendRedirect,
} from 'h3'
import { getAuthSettings, getSessionConfig } from '../../utils/auth'

export default defineEventHandler(async (event) => {
  const settings = getAuthSettings()
  if (!settings.enabled) {
    return sendRedirect(event, '/')
  }

  await clearSession(event, getSessionConfig(event))

  // The external Authelia session is managed by Nginx Proxy Manager and cannot
  // be ended from here without logging the user out of every other app.
  const forwarded = Boolean((getRequestHeader(event, 'remote-email') || '').trim())
  if (getMethod(event) === 'POST') {
    return { success: true, forward_auth: forwarded }
  }

  return sendRedirect(event, `/login?signed_out=1${forwarded ? '&forward_auth=1' : ''}`)
})

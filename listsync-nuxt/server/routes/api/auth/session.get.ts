import { defineEventHandler } from 'h3'
import { getAuthSettings, resolveAuth } from '../../../utils/auth'

export default defineEventHandler(async (event) => {
  const settings = getAuthSettings()
  const auth = await resolveAuth(event)

  return {
    authenticated: auth.authenticated,
    oidc_enabled: settings.enabled,
    email: auth.identity?.email || null,
    name: auth.identity?.name || null,
    source: auth.identity?.source || null,
    reason: auth.reason || null,
  }
})

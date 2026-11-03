import { validateAuthConfiguration } from '../utils/auth'

export default defineNitroPlugin(() => {
  const missing = validateAuthConfiguration()
  if (missing.length) {
    throw new Error(
      `OIDC is enabled but its configuration is incomplete. Missing or invalid: ${missing.join(', ')}`,
    )
  }
})

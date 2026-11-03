import {
  clearSession,
  defineEventHandler,
  getQuery,
  getRequestURL,
  sendRedirect,
  useSession,
} from 'h3'
import * as client from 'openid-client'
import {
  getAuthSettings,
  getOidcConfig,
  getSessionConfig,
  getTransactionConfig,
  isEmailAllowed,
  safeRedirect,
  type AuthSessionData,
  type OidcTransaction,
} from '../../../utils/auth'

function firstName(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

function groupList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.filter((entry): entry is string => typeof entry === 'string')
  }
  if (typeof value === 'string') {
    return value
      .split(/[,;]/)
      .map((entry) => entry.trim())
      .filter(Boolean)
  }
  return []
}

export default defineEventHandler(async (event) => {
  const settings = getAuthSettings()
  if (!settings.enabled) {
    return sendRedirect(event, '/')
  }

  const query = getQuery(event)
  if (query.error) {
    console.warn(`OIDC provider returned an error: ${String(query.error)}`)
    return sendRedirect(event, '/login?error=oidc')
  }

  const transactionConfig = getTransactionConfig(event)
  const transaction = await useSession<OidcTransaction>(event, transactionConfig)
  const transactionData = transaction.data
  await clearSession(event, transactionConfig)

  if (
    !transactionData?.state ||
    !transactionData.nonce ||
    !transactionData.code_verifier ||
    query.state !== transactionData.state
  ) {
    console.warn('OIDC callback rejected: missing or mismatched transaction state')
    return sendRedirect(event, '/login?error=invalid_state')
  }

  try {
    const config = await getOidcConfig()
    const currentUrl = getRequestURL(event, { xForwardedHost: true, xForwardedProto: true })
    const tokens = await client.authorizationCodeGrant(config, currentUrl, {
      pkceCodeVerifier: transactionData.code_verifier,
      expectedState: transactionData.state,
      expectedNonce: transactionData.nonce,
    })

    const claims: any = tokens.claims()
    let userInfo: any = null
    let email = firstName(claims?.email)
    let name = firstName(claims?.name) || firstName(claims?.preferred_username)
    let groups = groupList(claims?.groups)

    if ((!email || !name || !groups.length) && tokens.access_token) {
      try {
        userInfo = await client.fetchUserInfo(
          config,
          tokens.access_token,
          firstName(claims?.sub),
        )
        email = email || firstName(userInfo?.email)
        name = name || firstName(userInfo?.name) || firstName(userInfo?.preferred_username)
        groups = groups.length ? groups : groupList(userInfo?.groups)
      } catch (error) {
        console.warn('OIDC userinfo lookup failed; using ID token claims only:', error)
      }
    }

    if (!email) {
      console.warn('OIDC login rejected: provider did not return an email address')
      return sendRedirect(event, '/login?error=no_email')
    }
    if (!isEmailAllowed(email, settings)) {
      console.warn(`OIDC login rejected for unlisted email: ${email}`)
      return sendRedirect(event, '/login?error=not_allowed')
    }

    const issuedAt = Date.now()
    const expiresAt = issuedAt + Math.round(settings.sessionHours * 3600 * 1000)
    const session = await useSession<AuthSessionData>(event, getSessionConfig(event))
    await session.update({
      sub: firstName(claims?.sub) || firstName(userInfo?.sub),
      email,
      name,
      groups,
      auth_source: 'oidc',
      issued_at: issuedAt,
      expires_at: expiresAt,
    })

    return sendRedirect(event, safeRedirect(transactionData.redirect))
  } catch (error) {
    console.error('OIDC callback failed:', error)
    return sendRedirect(event, '/login?error=oidc')
  }
})

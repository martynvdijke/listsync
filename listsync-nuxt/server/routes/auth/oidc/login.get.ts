import { defineEventHandler, getQuery, sendRedirect, useSession } from 'h3'
import * as client from 'openid-client'
import {
  getAuthSettings,
  getOidcConfig,
  getTransactionConfig,
  safeRedirect,
  type OidcTransaction,
} from '../../../utils/auth'

export default defineEventHandler(async (event) => {
  const settings = getAuthSettings()
  if (!settings.enabled) {
    return sendRedirect(event, '/')
  }

  try {
    const config = await getOidcConfig()
    const state = client.randomState()
    const nonce = client.randomNonce()
    const codeVerifier = client.randomPKCECodeVerifier()
    const codeChallenge = await client.calculatePKCECodeChallenge(codeVerifier)
    const redirect = safeRedirect(getQuery(event).redirect)

    const transaction = await useSession<OidcTransaction>(event, getTransactionConfig(event))
    await transaction.update({
      state,
      nonce,
      code_verifier: codeVerifier,
      redirect,
      created_at: Date.now(),
    })

    const authorizationUrl = client.buildAuthorizationUrl(config, {
      redirect_uri: settings.redirectUri,
      scope: settings.scopes.join(' '),
      state,
      nonce,
      code_challenge: codeChallenge,
      code_challenge_method: 'S256',
    })
    return sendRedirect(event, authorizationUrl.href)
  } catch (error) {
    console.error('Could not start OIDC login:', error)
    return sendRedirect(event, '/login?error=oidc')
  }
})

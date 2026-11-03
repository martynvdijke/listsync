import { readFileSync } from 'node:fs'
import * as client from 'openid-client'
import {
  getRequestProtocol,
  getRequestHeader,
  getSession,
  type H3Event,
  type SessionConfig,
} from 'h3'

export type AuthSource = 'forward-auth' | 'oidc' | 'disabled'

export type AuthSessionData = {
  sub?: string
  email: string
  name?: string
  groups: string[]
  auth_source: AuthSource
  issued_at: number
  expires_at: number
}

export type AuthIdentity = {
  sub?: string
  email: string
  name?: string
  groups: string[]
  source: AuthSource
}

export type AuthResolution = {
  authenticated: boolean
  identity?: AuthIdentity
  reason?: 'unauthenticated' | 'not_allowed'
}

export type OidcSettings = {
  enabled: boolean
  issuer: string
  clientId: string
  clientSecret: string
  redirectUri: string
  scopes: string[]
  allowedEmails: string[]
  sessionPassword: string
  sessionHours: number
}

export type OidcTransaction = {
  state: string
  nonce: string
  code_verifier: string
  redirect: string
  created_at: number
}

function env(name: string): string {
  return (process.env[name] || '').trim()
}

function enabled(value: string): boolean {
  return ['1', 'true', 'yes', 'on'].includes(value.toLowerCase())
}

function splitList(value: string): string[] {
  return value
    .split(/[\s,;]+/)
    .map((entry) => entry.trim())
    .filter(Boolean)
}

function clientSecret(): string {
  const direct = env('OIDC_CLIENT_SECRET')
  if (direct) {
    return direct
  }

  const secretFile = env('OIDC_CLIENT_SECRET_FILE')
  if (!secretFile) {
    return ''
  }

  try {
    return readFileSync(secretFile, 'utf8').trim()
  } catch (error) {
    console.error(`Could not read OIDC_CLIENT_SECRET_FILE (${secretFile}):`, error)
    return ''
  }
}

let settingsCache: OidcSettings | null = null

export function getAuthSettings(): OidcSettings {
  if (settingsCache) {
    return settingsCache
  }

  const sessionHours = Number(env('OIDC_SESSION_HOURS') || '8')
  settingsCache = {
    enabled: enabled(env('OIDC_ENABLED')),
    issuer: (env('OIDC_ISSUER') || env('OIDC_ISSUER_URL')).replace(/\/+$/, ''),
    clientId: env('OIDC_CLIENT_ID'),
    clientSecret: clientSecret(),
    redirectUri: env('OIDC_REDIRECT_URI'),
    scopes: splitList(env('OIDC_SCOPES') || 'openid email profile groups'),
    allowedEmails: splitList(env('OIDC_ALLOWED_EMAILS') || env('OIDC_ALLOWED_EMAIL')).map((email) =>
      email.toLowerCase(),
    ),
    sessionPassword: env('NUXT_SESSION_PASSWORD'),
    sessionHours: Number.isFinite(sessionHours) && sessionHours > 0 ? sessionHours : 8,
  }
  return settingsCache
}

export function validateAuthConfiguration(): string[] {
  const settings = getAuthSettings()
  if (!settings.enabled) {
    return []
  }

  const missing: string[] = []
  if (!settings.issuer) missing.push('OIDC_ISSUER')
  if (!settings.clientId) missing.push('OIDC_CLIENT_ID')
  if (!settings.clientSecret) missing.push('OIDC_CLIENT_SECRET or OIDC_CLIENT_SECRET_FILE')
  if (!settings.redirectUri) missing.push('OIDC_REDIRECT_URI')
  if (!settings.allowedEmails.length) missing.push('OIDC_ALLOWED_EMAILS')
  if (!settings.sessionPassword) {
    missing.push('NUXT_SESSION_PASSWORD')
  } else if (settings.sessionPassword.length < 32) {
    missing.push('NUXT_SESSION_PASSWORD (must be at least 32 characters)')
  }
  return missing
}

let oidcConfigPromise: Promise<client.Configuration> | null = null

export function getOidcConfig(): Promise<client.Configuration> {
  if (!oidcConfigPromise) {
    const settings = getAuthSettings()
    oidcConfigPromise = client
      .discovery(
        new URL(settings.issuer),
        settings.clientId,
        {
          redirect_uris: [settings.redirectUri],
          response_types: ['code'],
          token_endpoint_auth_method: 'client_secret_basic',
        },
        client.ClientSecretBasic(settings.clientSecret),
      )
      .catch((error) => {
        // Do not cache a transient discovery failure forever.
        oidcConfigPromise = null
        throw error
      })
  }
  return oidcConfigPromise
}

function isSecureRequest(event: H3Event): boolean {
  return getRequestProtocol(event, { xForwardedProto: true }) === 'https'
}

export function getSessionConfig(event: H3Event): SessionConfig {
  const settings = getAuthSettings()
  return {
    name: 'listsync-session',
    password: settings.sessionPassword,
    maxAge: Math.round(settings.sessionHours * 3600),
    cookie: {
      httpOnly: true,
      sameSite: 'lax',
      secure: isSecureRequest(event),
      path: '/',
    },
  }
}

export function getTransactionConfig(event: H3Event): SessionConfig {
  const settings = getAuthSettings()
  return {
    name: 'listsync-oidc-tx',
    password: settings.sessionPassword,
    maxAge: 10 * 60,
    cookie: {
      httpOnly: true,
      sameSite: 'lax',
      secure: isSecureRequest(event),
      path: '/auth/oidc',
    },
  }
}

export function isEmailAllowed(email: string, settings = getAuthSettings()): boolean {
  return settings.allowedEmails.includes(email.trim().toLowerCase())
}

function groupsFromHeader(value: string | undefined): string[] {
  if (!value) return []
  return value
    .split(/[,;]/)
    .map((group) => group.trim())
    .filter(Boolean)
}

export async function resolveAuth(event: H3Event): Promise<AuthResolution> {
  const settings = getAuthSettings()

  // When OIDC is disabled, preserve ListSync's previous open behaviour.
  if (!settings.enabled) {
    return {
      authenticated: true,
      identity: { email: '', groups: [], source: 'disabled' },
    }
  }

  // Nginx Proxy Manager's Authelia snippet injects these headers after it has
  // authenticated the request. This is trusted only because the app's ports
  // are not published; see the deployment notes.
  const forwardedEmail = (getRequestHeader(event, 'remote-email') || '').trim()
  if (forwardedEmail) {
    if (!isEmailAllowed(forwardedEmail, settings)) {
      return { authenticated: false, reason: 'not_allowed' }
    }
    return {
      authenticated: true,
      identity: {
        email: forwardedEmail,
        name: (getRequestHeader(event, 'remote-name') || '').trim() || undefined,
        groups: groupsFromHeader(getRequestHeader(event, 'remote-groups')),
        source: 'forward-auth',
      },
    }
  }

  try {
    const session = await getSession<AuthSessionData>(event, getSessionConfig(event))
    const data = session.data
    if (data?.email && Number(data.expires_at) > Date.now()) {
      if (!isEmailAllowed(data.email, settings)) {
        return { authenticated: false, reason: 'not_allowed' }
      }
      return {
        authenticated: true,
        identity: {
          sub: data.sub,
          email: data.email,
          name: data.name,
          groups: Array.isArray(data.groups) ? data.groups : [],
          source: 'oidc',
        },
      }
    }
  } catch (error) {
    // An invalid or expired cookie is an unauthenticated request, not a 500.
    console.debug('Ignoring invalid ListSync auth session cookie:', error)
  }

  return { authenticated: false, reason: 'unauthenticated' }
}

export function safeRedirect(value: unknown): string {
  if (typeof value !== 'string' || !value) {
    return '/'
  }
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) {
    return '/'
  }
  if (value === '/login' || value.startsWith('/login?') || value.startsWith('/login/')) {
    return '/'
  }
  if (value.startsWith('/auth/')) {
    return '/'
  }
  return value
}

export function isPublicPath(pathname: string): boolean {
  if (pathname === '/login' || pathname.startsWith('/login/')) return true
  if (pathname === '/api/auth/session') return true
  if (pathname === '/api/system/health') return true
  if (pathname === '/favicon.ico' || pathname === '/robots.txt') return true
  if (pathname.startsWith('/_nuxt/') || pathname === '/__nuxt' || pathname.startsWith('/_ipx/')) {
    return true
  }
  return pathname === '/auth' || pathname.startsWith('/auth/')
}

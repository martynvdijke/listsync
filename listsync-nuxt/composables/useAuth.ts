export type AuthSession = {
  authenticated: boolean
  oidc_enabled: boolean
  email: string | null
  name: string | null
  source: 'forward-auth' | 'oidc' | 'disabled' | null
  reason: string | null
}

const emptySession = (): AuthSession => ({
  authenticated: false,
  oidc_enabled: false,
  email: null,
  name: null,
  source: null,
  reason: null,
})

export function useAuth() {
  const session = useState<AuthSession>('listsync-auth-session', emptySession)
  const loading = useState<boolean>('listsync-auth-loading', () => false)
  const loaded = useState<boolean>('listsync-auth-loaded', () => false)

  async function loadAuth(force = false): Promise<AuthSession> {
    if (loading.value) return session.value
    if (loaded.value && !force) return session.value

    loading.value = true
    try {
      session.value = await $fetch<AuthSession>('/api/auth/session')
      loaded.value = true
    } catch (error) {
      console.error('Could not load authentication state:', error)
      session.value = emptySession()
    } finally {
      loading.value = false
    }
    return session.value
  }

  async function signOut(): Promise<void> {
    loading.value = true
    try {
      await $fetch('/auth/logout', { method: 'POST' })
    } catch (error) {
      console.error('Could not sign out:', error)
    } finally {
      session.value = { ...emptySession(), oidc_enabled: session.value.oidc_enabled }
      loaded.value = true
      loading.value = false
    }
    await navigateTo('/login?signed_out=1')
  }

  return {
    session,
    loading,
    loadAuth,
    signOut,
  }
}

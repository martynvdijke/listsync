<template>
  <div class="setup-background flex min-h-screen items-center justify-center p-4">
    <div class="setup-lines">
      <div v-for="i in 10" :key="i" class="setup-line" :style="{ animationDelay: `${i * 0.5}s` }"></div>
    </div>

    <div class="relative z-10 w-full max-w-md">
      <div class="glass-card rounded-2xl border border-purple-500/20 p-8 shadow-2xl">
        <div class="mb-8 flex flex-col items-center text-center">
          <div class="mb-4 flex h-16 w-16 items-center justify-center overflow-hidden rounded-xl bg-purple-500/20">
            <img :src="logoImage" alt="ListSync Logo" class="h-14 w-14 object-contain" />
          </div>
          <h1 class="titillium-web-bold text-3xl font-bold text-foreground">ListSync</h1>
          <p class="mt-2 text-sm text-muted-foreground">Sign in to manage your media lists.</p>
        </div>

        <div v-if="signedOut" class="mb-5 rounded-lg border border-green-500/30 bg-green-500/10 p-3 text-sm text-green-300">
          You have signed out of ListSync.
          <span v-if="forwardAuthSignedOut" class="mt-1 block text-xs text-green-200/80">
            Your Authelia session is still active, so signing in again will not ask for your password.
          </span>
        </div>

        <div v-if="errorMessage" class="mb-5 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {{ errorMessage }}
        </div>

        <a
          :href="loginUrl"
          class="flex w-full items-center justify-center gap-2 rounded-lg bg-purple-600 px-4 py-3 font-semibold text-white transition-colors hover:bg-purple-500 focus:outline-none focus:ring-2 focus:ring-purple-400 focus:ring-offset-2 focus:ring-offset-black"
        >
          <LogInIcon :size="18" />
          Sign in with Authelia
        </a>

        <div v-if="session.authenticated && session.oidc_enabled" class="mt-5 rounded-lg border border-purple-500/20 bg-black/20 p-3 text-center text-sm">
          <p class="text-muted-foreground">
            Already signed in as
            <span class="font-medium text-foreground">{{ session.email }}</span>
          </p>
          <NuxtLink to="/" class="mt-2 inline-block font-semibold text-purple-300 hover:text-purple-200">
            Continue to ListSync
          </NuxtLink>
        </div>

        <p class="mt-6 text-center text-xs text-muted-foreground">
          Access is restricted to authorised accounts.
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { LogIn as LogInIcon } from 'lucide-vue-next'
import logoImage from '~/assets/images/list-sync-logo.webp'

definePageMeta({
  layout: false,
})

useHead({
  title: 'Sign in - ListSync',
})

const route = useRoute()
const { session, loadAuth } = useAuth()

const signedOut = computed(() => route.query.signed_out === '1')
const forwardAuthSignedOut = computed(() => route.query.forward_auth === '1')

const errorMessage = computed(() => {
  switch (route.query.error) {
    case 'not_allowed':
      return 'This account is not authorised to use ListSync. Contact the administrator if you believe this is a mistake.'
    case 'invalid_state':
      return 'The sign-in request expired or could not be verified. Please try again.'
    case 'no_email':
      return 'Authelia did not return an email address, so ListSync cannot authorise this account.'
    case 'oidc':
      return 'Sign-in could not be completed. Please try again.'
    default:
      return ''
  }
})

function safeRedirect(value: unknown): string {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) {
    return '/'
  }
  if (value === '/login' || value.startsWith('/login?') || value.startsWith('/auth/')) {
    return '/'
  }
  return value
}

const redirectTarget = computed(() => safeRedirect(route.query.redirect))
const loginUrl = computed(
  () => `/auth/oidc/login?redirect=${encodeURIComponent(redirectTarget.value)}`,
)

onMounted(() => {
  loadAuth()
})
</script>

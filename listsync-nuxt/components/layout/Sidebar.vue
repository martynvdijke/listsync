<template>
  <aside :class="sidebarClasses">
    <!-- Logo / Header -->
    <div :class="['flex items-center border-b border-purple-500/20 py-6 transition-all duration-300', uiStore.sidebarCollapsed ? 'justify-center px-3' : 'justify-between px-6']">
      <NuxtLink to="/" class="flex items-center gap-3 text-foreground hover:text-purple-400 transition-colors">
        <div class="flex items-center justify-center w-12 h-12 rounded-lg bg-purple-500/20 overflow-hidden flex-shrink-0">
          <img 
            :src="logoImage" 
            alt="ListSync Logo" 
            class="w-10 h-10 object-contain"
          />
        </div>
        <span v-if="!uiStore.sidebarCollapsed" class="text-2xl font-bold titillium-web-bold">
          ListSync
        </span>
      </NuxtLink>

      <!-- Collapse Toggle (Desktop) -->
      <button
        v-if="!isMobile && !uiStore.sidebarCollapsed"
        type="button"
        class="p-2 rounded-lg hover:bg-white/5 transition-colors text-muted-foreground hover:text-foreground"
        @click="uiStore.toggleSidebar"
        :aria-label="uiStore.sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
      >
        <component :is="uiStore.sidebarCollapsed ? ChevronRightIcon : ChevronLeftIcon" :size="20" />
      </button>

      <!-- Close Button (Mobile) -->
      <button
        v-if="isMobile"
        type="button"
        class="p-2 rounded-lg hover:bg-white/5 transition-colors text-muted-foreground hover:text-foreground lg:hidden"
        @click="uiStore.closeMobileMenu"
        aria-label="Close menu"
      >
        <component :is="XIcon" :size="20" />
      </button>
    </div>
    
    <!-- Expand Button (When Collapsed) -->
    <div v-if="!isMobile && uiStore.sidebarCollapsed" class="flex justify-center px-3 py-2">
      <button
        type="button"
        class="p-2 rounded-lg hover:bg-white/5 transition-colors text-muted-foreground hover:text-foreground"
        @click="uiStore.toggleSidebar"
        aria-label="Expand sidebar"
      >
        <component :is="ChevronRightIcon" :size="20" />
      </button>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 px-3 py-6 space-y-1 overflow-y-auto custom-scrollbar">
      <NuxtLink
        v-for="item in navigation"
        :key="item.path"
        :to="item.path"
        :class="navItemClasses(item.path)"
        @click="handleNavClick"
      >
        <component :is="item.icon" :size="20" />
        <span v-if="!uiStore.sidebarCollapsed" class="flex-1">
          {{ item.label }}
        </span>
      </NuxtLink>
    </nav>

    <!-- Signed-in user -->
    <div v-if="authSession.authenticated && authSession.oidc_enabled" class="px-3 py-3 border-t border-purple-500/20">
      <div v-if="!uiStore.sidebarCollapsed" :class="footerClasses">
        <div class="flex items-center gap-2.5">
          <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-purple-500/20">
            <UserRoundIcon :size="16" class="text-purple-300" />
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-xs font-bold text-foreground">
              {{ authSession.name || authSession.email }}
            </p>
            <p class="truncate text-[10px] font-medium text-muted-foreground">
              {{ authSession.source === 'forward-auth' ? 'Signed in via Authelia' : 'Signed in with OIDC' }}
            </p>
          </div>
          <button
            type="button"
            class="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground disabled:opacity-50"
            :disabled="signingOut"
            title="Sign out"
            aria-label="Sign out"
            @click="handleSignOut"
          >
            <LogOutIcon :size="15" />
          </button>
        </div>
      </div>
      <button
        v-else
        type="button"
        class="mx-auto flex rounded-lg p-2 text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground disabled:opacity-50"
        :disabled="signingOut"
        title="Sign out"
        aria-label="Sign out"
        @click="handleSignOut"
      >
        <LogOutIcon :size="18" />
      </button>
    </div>

    <!-- Sync Status -->
    <div v-if="systemStore.health" class="px-3 py-3 border-t border-purple-500/20">
      <div :class="footerClasses">
        <div class="flex items-center gap-2.5">
          <div :class="syncStatusDotClass" />
          <div v-if="!uiStore.sidebarCollapsed" class="flex-1 min-w-0">
            <p class="text-xs font-bold text-foreground uppercase tracking-wide">Sync Status</p>
            <p class="text-[10px] text-muted-foreground truncate font-medium">
              {{ syncStatusText }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Footer (System Status) -->
    <div class="px-3 py-4 border-t border-purple-500/20">
      <div :class="footerClasses">
        <div class="flex items-center gap-2.5">
          <div :class="statusDotClass" />
          <div v-if="!uiStore.sidebarCollapsed" class="flex-1 min-w-0">
            <p class="text-xs font-bold text-foreground uppercase tracking-wide">System Status</p>
            <p class="text-[10px] text-muted-foreground truncate font-medium">
              {{ systemStore.isHealthy ? 'All systems operational' : 'Issues detected' }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import {
  LayoutDashboard as DashboardIcon,
  List as ListIcon,
  FolderKanban as CollectionsIcon,
  RefreshCw as SyncIcon,
  History as HistoryIcon,
  Settings as SettingsIcon,
  Database as DatabaseIcon,
  FileText as LogsIcon,
  ChevronLeft as ChevronLeftIcon,
  ChevronRight as ChevronRightIcon,
  X as XIcon,
  UserRound as UserRoundIcon,
  LogOut as LogOutIcon,
} from 'lucide-vue-next'
import logoImage from '~/assets/images/list-sync-logo.webp'

const route = useRoute()
const uiStore = useUIStore()
const systemStore = useSystemStore()
const syncStore = useSyncStore()
const { session: authSession, loadAuth, signOut } = useAuth()

const isMobile = ref(false)
const signingOut = ref(false)

const navigation = [
  {
    label: 'Dashboard',
    path: '/',
    icon: DashboardIcon,
  },
  {
    label: 'Lists',
    path: '/lists',
    icon: ListIcon,
  },
  {
    label: 'Collections',
    path: '/collections',
    icon: CollectionsIcon,
  },
  {
    label: 'Items',
    path: '/items',
    icon: DatabaseIcon,
  },
  {
    label: 'Sync',
    path: '/sync',
    icon: SyncIcon,
  },
  {
    label: 'Sync History',
    path: '/sync-history',
    icon: HistoryIcon,
  },
  {
    label: 'Live Logs',
    path: '/logs',
    icon: LogsIcon,
  },
  {
    label: 'Settings',
    path: '/settings',
    icon: SettingsIcon,
  },
]

const sidebarClasses = computed(() => {
  const baseClasses = [
    'flex flex-col h-screen',
    'glass-sidebar',
    'transition-all duration-300',
  ]

  // Width classes
  if (uiStore.sidebarCollapsed) {
    baseClasses.push('w-20')
  } else {
    baseClasses.push('w-64')
  }

  // Mobile: hide when closed, show when open
  if (!uiStore.mobileMenuOpen) {
    // Hidden on mobile when closed, visible on desktop
    baseClasses.push('hidden lg:flex lg:relative lg:z-20')
  } else {
    // Visible on mobile when open
    baseClasses.push('fixed inset-y-0 left-0 z-40 lg:relative lg:z-20')
  }

  return baseClasses.join(' ')
})

const navItemClasses = (path: string) => {
  // Exact match for most pages, but handle special cases
  let isActive = route.path === path
  
  // For root path, only match exactly
  if (path === '/') {
    isActive = route.path === '/'
  }
  // For other paths, check if route starts with path but not if it's a longer path
  // e.g., /sync should not match /sync-history
  else {
    isActive = route.path === path
  }
  
  const baseClasses = [
    'flex items-center gap-3 px-3 py-2.5 rounded-lg',
    'text-sm font-medium',
    'transition-all duration-200',
    'group',
  ]

  if (uiStore.sidebarCollapsed) {
    baseClasses.push('justify-center')
  }

  if (isActive) {
    baseClasses.push(
      'bg-purple-500/20',
      'text-purple-300',
      'border border-purple-500/30'
    )
  } else {
    baseClasses.push(
      'text-muted-foreground',
      'hover:bg-white/5',
      'hover:text-foreground',
      'border border-transparent'
    )
  }

  return baseClasses.join(' ')
}

const footerClasses = computed(() => {
  const baseClasses = [
    'p-3 rounded-lg',
    'bg-black/20',
    'border border-purple-500/10',
  ]

  if (uiStore.sidebarCollapsed) {
    baseClasses.push('flex justify-center')
  }

  return baseClasses.join(' ')
})

const syncStatusDotClass = computed(() => {
  const baseClasses = ['w-2 h-2 rounded-full']
  // Use syncStore for real-time sync status instead of systemStore
  const isRunning = syncStore.isSyncing || syncStore.liveSyncStatus?.is_running || false
  
  if (isRunning) {
    baseClasses.push('bg-purple-500 animate-pulse')
  } else {
    baseClasses.push('bg-green-500 pulse-glow')
  }

  return baseClasses.join(' ')
})

const syncStatusText = computed(() => {
  // Use syncStore for real-time sync status instead of systemStore
  const isRunning = syncStore.isSyncing || syncStore.liveSyncStatus?.is_running || false
  
  if (isRunning) {
    const syncType = syncStore.liveSyncStatus?.sync_type
    return syncType === 'single' ? 'Syncing list' : 'Syncing all'
  } else {
    return 'Idle'
  }
})

const statusDotClass = computed(() => {
  const baseClasses = ['w-2 h-2 rounded-full']
  
  if (systemStore.isHealthy) {
    baseClasses.push('bg-green-500 pulse-glow')
  } else {
    baseClasses.push('bg-red-500 animate-pulse')
  }

  return baseClasses.join(' ')
})

const handleNavClick = () => {
  if (isMobile.value) {
    uiStore.closeMobileMenu()
  }
}

const handleSignOut = async () => {
  if (signingOut.value) return
  signingOut.value = true
  try {
    await signOut()
  } finally {
    signingOut.value = false
  }
}

// Check if mobile on mount and resize
const checkMobile = () => {
  if (process.client) {
    isMobile.value = window.innerWidth < 1024
  }
}

onMounted(() => {
  checkMobile()
  if (process.client) {
    window.addEventListener('resize', checkMobile)
    
    // Fetch system health
    systemStore.checkHealth()
    loadAuth()
  }
})

onUnmounted(() => {
  if (process.client) {
    window.removeEventListener('resize', checkMobile)
  }
})
</script>


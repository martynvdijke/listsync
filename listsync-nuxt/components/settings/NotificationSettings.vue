<template>
  <Card class="glass-card border border-purple-500/30 hover:border-purple-400/50 transition-all duration-300">
    <div class="space-y-6">
      <!-- Main Header -->
      <div class="flex items-center gap-2.5">
        <div class="p-2 rounded-lg bg-gradient-to-br from-purple-600/20 to-purple-500/10 border border-purple-500/30">
          <BellIcon class="w-4 h-4 text-purple-400" />
        </div>
        <div>
          <h3 class="text-base font-bold titillium-web-semibold">
            Notification Settings
          </h3>
          <p class="text-[10px] text-muted-foreground font-medium">
            Configure notification preferences
          </p>
        </div>
      </div>

      <!-- Discord Section -->
      <div class="p-4 rounded-lg bg-gradient-to-br from-purple-600/20 to-purple-500/10 border border-purple-500/25 space-y-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <MessageSquareIcon class="w-4 h-4 text-purple-400" />
            <span class="text-xs font-bold text-purple-300 uppercase tracking-wide">Discord</span>
          </div>
          <Button
            variant="secondary"
            size="sm"
            :loading="isTestingDiscord"
            @click="onTestDiscord"
          >
            <SendIcon class="w-4 h-4 mr-2" />
            Send Test
          </Button>
        </div>

        <div>
          <label class="block text-xs font-semibold mb-2 text-foreground">
            Discord Webhook URL
          </label>
          <Input
            v-model="localValue.discordWebhook"
            type="url"
            placeholder="https://discord.com/api/webhooks/..."
            :icon="MessageSquareIcon"
            @update:model-value="emitUpdate"
          />
          <p class="text-xs text-muted-foreground mt-1.5">
            Get notified in Discord when sync completes
          </p>
        </div>

        <div>
          <label class="block text-xs font-semibold mb-2 text-foreground">
            Discord Notifications
          </label>
          <div class="flex items-center gap-3">
            <span
              :class="[
                'text-sm font-semibold tabular-nums',
                localValue.discordEnabled ? 'text-green-400' : 'text-gray-400'
              ]"
            >
              {{ localValue.discordEnabled ? 'ON' : 'OFF' }}
            </span>
            <button
              type="button"
              role="switch"
              :aria-checked="localValue.discordEnabled"
              :class="[
                'relative inline-flex h-7 w-14 items-center rounded-full transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-black',
                localValue.discordEnabled ? 'bg-green-500' : 'bg-gray-600'
              ]"
              @click="toggleDiscord"
            >
              <span
                :class="[
                  'inline-flex items-center justify-center h-6 w-6 transform rounded-full bg-white shadow-lg transition-all duration-200',
                  localValue.discordEnabled ? 'translate-x-7' : 'translate-x-0.5'
                ]"
              >
                <CheckIcon v-if="localValue.discordEnabled" :size="14" class="text-green-500" />
                <XIcon v-else :size="14" class="text-gray-600" />
              </span>
            </button>
            <span class="text-sm text-muted-foreground">
              {{ localValue.discordEnabled ? 'Enabled' : 'Disabled' }}
            </span>
          </div>
          <p class="text-xs text-muted-foreground mt-1.5">
            Send sync completion summary to Discord
          </p>
        </div>
      </div>

      <!-- Gotify Section -->
      <div class="p-4 rounded-lg bg-gradient-to-br from-purple-600/20 to-purple-500/10 border border-purple-500/25 space-y-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <ServerIcon class="w-4 h-4 text-purple-400" />
            <span class="text-xs font-bold text-purple-300 uppercase tracking-wide">Gotify</span>
          </div>
          <Button
            variant="secondary"
            size="sm"
            :loading="isTestingGotify"
            @click="onTestGotify"
          >
            <SendIcon class="w-4 h-4 mr-2" />
            Send Test
          </Button>
        </div>

        <div>
          <label class="block text-xs font-semibold mb-2 text-foreground">
            Gotify Server URL
          </label>
          <Input
            v-model="localValue.gotifyUrl"
            type="url"
            placeholder="https://gotify.example.com"
            :icon="ServerIcon"
            @update:model-value="emitUpdate"
          />
          <p class="text-xs text-muted-foreground mt-1.5">
            Base URL of your self-hosted Gotify server
          </p>
        </div>

        <div>
          <label class="block text-xs font-semibold mb-2 text-foreground">
            Gotify App Token
          </label>
          <Input
            v-model="localValue.gotifyToken"
            type="password"
            placeholder="••••••••••••••••"
            :icon="KeyRoundIcon"
            @update:model-value="emitUpdate"
          />
          <p class="text-xs text-muted-foreground mt-1.5">
            Gotify application token — create one in your Gotify dashboard under Apps
          </p>
        </div>

        <div>
          <label class="block text-xs font-semibold mb-2 text-foreground">
            Gotify Notifications
          </label>
          <div class="flex items-center gap-3">
            <span
              :class="[
                'text-sm font-semibold tabular-nums',
                localValue.gotifyEnabled ? 'text-green-400' : 'text-gray-400'
              ]"
            >
              {{ localValue.gotifyEnabled ? 'ON' : 'OFF' }}
            </span>
            <button
              type="button"
              role="switch"
              :aria-checked="localValue.gotifyEnabled"
              :class="[
                'relative inline-flex h-7 w-14 items-center rounded-full transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-black',
                localValue.gotifyEnabled ? 'bg-green-500' : 'bg-gray-600'
              ]"
              @click="toggleGotify"
            >
              <span
                :class="[
                  'inline-flex items-center justify-center h-6 w-6 transform rounded-full bg-white shadow-lg transition-all duration-200',
                  localValue.gotifyEnabled ? 'translate-x-7' : 'translate-x-0.5'
                ]"
              >
                <CheckIcon v-if="localValue.gotifyEnabled" :size="14" class="text-green-500" />
                <XIcon v-else :size="14" class="text-gray-600" />
              </span>
            </button>
            <span class="text-sm text-muted-foreground">
              {{ localValue.gotifyEnabled ? 'Enabled' : 'Disabled' }}
            </span>
          </div>
          <p class="text-xs text-muted-foreground mt-1.5">
            Send sync completion summary to Gotify
          </p>
        </div>
      </div>
    </div>
  </Card>
</template>

<script setup lang="ts">
import {
  Bell as BellIcon,
  Send as SendIcon,
  MessageSquare as MessageSquareIcon,
  Check as CheckIcon,
  X as XIcon,
  KeyRound as KeyRoundIcon,
  Server as ServerIcon,
} from 'lucide-vue-next'

interface NotificationSettings {
  discordWebhook: string
  discordEnabled: boolean
  gotifyUrl: string
  gotifyToken: string
  gotifyEnabled: boolean
}

interface Props {
  modelValue: NotificationSettings
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:modelValue': [value: NotificationSettings]
  'test-discord': []
  'test-gotify': []
}>()

const localValue = ref({ ...props.modelValue })
const isTestingDiscord = ref(false)
const isTestingGotify = ref(false)

// Watch for external changes
watch(
  () => props.modelValue,
  (newValue) => {
    localValue.value = { ...newValue }
  },
  { deep: true }
)

// Emit updates
const emitUpdate = () => {
  emit('update:modelValue', { ...localValue.value })
}

// Toggle functions
const toggleDiscord = () => {
  localValue.value.discordEnabled = !localValue.value.discordEnabled
  emitUpdate()
}

const toggleGotify = () => {
  localValue.value.gotifyEnabled = !localValue.value.gotifyEnabled
  emitUpdate()
}

const onTestDiscord = () => {
  emit('test-discord')
}

const onTestGotify = () => {
  emit('test-gotify')
}

// Expose testing state setters for parent if needed via events — parent handles toast
defineExpose({ isTestingDiscord, isTestingGotify })
</script>

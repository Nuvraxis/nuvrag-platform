'use server'

import type { WidgetTheme } from '@rag/api-client'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'

import { type ActionState, failed, fromError, succeeded } from '@/lib/action-state'
import { authenticatedApi } from '@/lib/api'
import {
  chatbotStatus,
  generationConfig,
  number,
  nuvragMemRetentionDays,
  optionalText,
  originList,
  retentionDays,
  text,
  usageCap,
} from '@/lib/form'

/** The plaintext secret exists only in this response, so the form renders it once. */
export interface CreatedChatbot {
  id: string
  name: string
  slug: string
  secretKey: string
}

export interface RotatedSecret {
  secretKey: string
}

export async function createChatbotAction(
  _previous: ActionState<CreatedChatbot>,
  formData: FormData,
): Promise<ActionState<CreatedChatbot>> {
  const name = text(formData, 'name')
  if (!name) {
    return failed('Give the chatbot a name.', { name: 'A name is required.' })
  }

  const api = await authenticatedApi()
  try {
    // No slug is sent: the API derives it from the name, so two chatbots called "Support"
    // become `support` and `support-2` without the dashboard having to guess.
    const created = await api.createChatbot({
      name,
      description: optionalText(formData, 'description'),
      system_prompt: text(formData, 'system_prompt'),
      allowed_origins: originList(formData, 'allowed_origins'),
      model_config_json: generationConfig(formData),
      retention_days: retentionDays(formData),
      nuvrag_mem_retention_days: nuvragMemRetentionDays(formData),
      monthly_ingestion_unit_cap: usageCap(formData, 'monthly_ingestion_unit_cap'),
      monthly_retrieval_call_cap: usageCap(formData, 'monthly_retrieval_call_cap'),
      usage_cap_message: text(formData, 'usage_cap_message'),
      // Empty on purpose. The footer links are edited on the design tab beside the widget
      // preview that shows them, so the create form does not ask for them — a chatbot starts
      // with none, exactly as it starts with no theme.
      privacy_url: '',
      terms_url: '',
    })

    revalidatePath('/chatbots')
    return succeeded(`${created.chatbot.name} is ready.`, {
      id: created.chatbot.id,
      name: created.chatbot.name,
      slug: created.chatbot.slug,
      secretKey: created.secret.secret_key,
    })
  } catch (error) {
    return fromError(error)
  }
}

export async function updateChatbotAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const chatbotId = text(formData, 'chatbot_id')
  const name = text(formData, 'name')
  if (!chatbotId) {
    return failed('Missing chatbot reference.')
  }
  if (!name) {
    return failed('Give the chatbot a name.', { name: 'A name is required.' })
  }

  const api = await authenticatedApi()
  try {
    await api.updateChatbot(chatbotId, {
      name,
      // Empty string rather than null: the API drops null members from a patch, so sending
      // null would silently leave the old description in place instead of clearing it.
      description: text(formData, 'description'),
      system_prompt: text(formData, 'system_prompt'),
      allowed_origins: originList(formData, 'allowed_origins'),
      model_config_json: generationConfig(formData),
      // Null here means "keep forever" rather than "unchanged" — the two fields the API
      // treats that way, and what makes either retention something a tenant can switch off.
      retention_days: retentionDays(formData),
      nuvrag_mem_retention_days: nuvragMemRetentionDays(formData),
      // Null removes a cap rather than leaving it alone, the same exception the two
      // retention fields get.
      monthly_ingestion_unit_cap: usageCap(formData, 'monthly_ingestion_unit_cap'),
      monthly_retrieval_call_cap: usageCap(formData, 'monthly_retrieval_call_cap'),
      usage_cap_message: text(formData, 'usage_cap_message'),
      status: chatbotStatus(formData, 'status'),
    })
  } catch (error) {
    return fromError(error)
  }

  revalidatePath('/chatbots')
  revalidatePath(`/chatbots/${chatbotId}`, 'layout')
  return succeeded('Settings saved.')
}

export async function updateChatbotThemeAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const chatbotId = text(formData, 'chatbot_id')
  if (!chatbotId) {
    return failed('Missing chatbot reference.')
  }

  // Resetting is the same request with an empty body rather than an action of its own: an
  // empty theme is exactly what makes the widget fall back to its own stylesheet, dark-mode
  // switching included.
  const resetting = text(formData, 'intent') === 'reset'
  const theme = resetting ? {} : themeFromForm(formData)

  const api = await authenticatedApi()
  try {
    await api.updateChatbot(chatbotId, {
      theme_json: theme,
      // Deliberately omitted on a reset. The footer links are their own columns rather than
      // theme members precisely so that discarding a palette cannot discard a tenant's
      // privacy notice with it, and an absent field is how the API is told "unchanged".
      // Empty strings on a normal save clear them, which is the only way to remove one.
      ...(resetting
        ? {}
        : {
            privacy_url: text(formData, 'privacy_url'),
            terms_url: text(formData, 'terms_url'),
          }),
    })
  } catch (error) {
    return fromError(error)
  }

  revalidatePath(`/chatbots/${chatbotId}`, 'layout')
  return succeeded(
    Object.keys(theme).length === 0 ? 'Back to the default look.' : 'Appearance saved.',
  )
}

/**
 * Header and greeting are omitted when blank rather than sent as empty strings: absent means
 * "use the chatbot's name and the generated greeting", which is not the same as a widget
 * whose header is genuinely empty.
 */
function themeFromForm(formData: FormData): WidgetTheme {
  const title = text(formData, 'title')
  const greeting = text(formData, 'greeting')

  return {
    accent: text(formData, 'accent'),
    accent_foreground: text(formData, 'accent_foreground'),
    surface: text(formData, 'surface'),
    surface_muted: text(formData, 'surface_muted'),
    border: text(formData, 'border'),
    text: text(formData, 'text'),
    text_muted: text(formData, 'text_muted'),
    radius: Math.round(number(formData, 'radius', 16)),
    scheme: themeScheme(formData),
    position: text(formData, 'position') === 'left' ? 'left' : 'right',
    ...(title ? { title } : {}),
    ...(greeting ? { greeting } : {}),
  }
}

function themeScheme(formData: FormData): WidgetTheme['scheme'] {
  const value = text(formData, 'scheme')
  return value === 'light' || value === 'dark' ? value : 'system'
}

export async function rotateSecretAction(
  _previous: ActionState<RotatedSecret>,
  formData: FormData,
): Promise<ActionState<RotatedSecret>> {
  const chatbotId = text(formData, 'chatbot_id')
  if (!chatbotId) {
    return failed('Missing chatbot reference.')
  }

  const api = await authenticatedApi()
  try {
    const rotated = await api.rotateSecret(chatbotId)
    return succeeded('A new secret key has been issued.', { secretKey: rotated.secret_key })
  } catch (error) {
    return fromError(error)
  }
}

export async function deleteChatbotAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const chatbotId = text(formData, 'chatbot_id')
  if (!chatbotId) return failed('That chatbot could not be identified.')

  const api = await authenticatedApi()
  try {
    await api.deleteChatbot(chatbotId)
  } catch (error) {
    return fromError(error)
  }

  // Outside the try: `redirect` reports itself by throwing, and catching that would turn a
  // successful delete into an error message.
  revalidatePath('/chatbots')
  redirect('/chatbots')
}

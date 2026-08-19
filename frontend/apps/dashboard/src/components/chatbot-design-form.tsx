'use client'

import type { Chatbot } from '@rag/api-client'
import {
  Alert,
  AlertDescription,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Field,
  FieldDescription,
  FieldGroup,
  FieldLegend,
  FieldSet,
  Input,
  NativeSelect,
} from '@rag/ui'
import { useActionState, useEffect, useRef } from 'react'

import { type ActionState, idle } from '@/lib/action-state'
import { updateChatbotThemeAction } from '@/lib/actions/chatbots'
import { widgetThemeSchema } from '@/lib/schemas'
import { useActionForm } from '@/lib/use-action-form'
import { useActionToast } from '@/lib/use-action-toast'
import { BRAND_COLOURS, PANEL_COLOURS, themeFormDefaults } from '@/lib/widget-theme'

import { ColourField } from './colour-field'
import { ConfirmSubmit } from './confirm-submit'
import { FormField } from './form-field'
import { SubmitButton } from './submit-button'
import { WidgetPreview } from './widget-preview'

const SCHEME_HINT: Record<string, string> = {
  system: 'Follows the visitor’s own light or dark setting — but only for colours you leave alone.',
  light: 'Always the light palette.',
  dark: 'Always the dark palette.',
}

export function ChatbotDesignForm({ chatbot }: { chatbot: Chatbot }) {
  const { form, state, formProps } = useActionForm({
    action: updateChatbotThemeAction,
    schema: widgetThemeSchema,
    defaultValues: themeFormDefaults(chatbot.theme_json, chatbot),
  })

  // The reset gets its own state here rather than going through `<ActionForm>`, because this
  // component has to know it happened: React Hook Form reads `defaultValues` once, at mount,
  // so the controls have to be told to go back to the widget's own colours. Remounting on a
  // key would do that too, but it would take the component that announces the outcome with
  // it and the reset would happen silently.
  const [resetState, resetAction] = useActionState<ActionState, FormData>(
    updateChatbotThemeAction,
    idle,
  )
  useActionToast(resetState)

  const announced = useRef<ActionState | null>(null)
  useEffect(() => {
    if (announced.current === resetState) return
    announced.current = resetState
    if (resetState.status !== 'success') return
    // The reset request deliberately leaves the footer links alone, so the form has to as
    // well — reading them back from the live fields rather than from `chatbot`, which is the
    // server snapshot from page load and may be a save behind.
    form.reset(
      themeFormDefaults(undefined, {
        privacy_url: form.getValues('privacy_url'),
        terms_url: form.getValues('terms_url'),
      }),
    )
  }, [resetState, form])

  const values = form.watch()

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
      <form {...formProps}>
        <input type="hidden" name="chatbot_id" value={chatbot.id} />

        <Card>
          <CardHeader>
            <div className="space-y-1">
              <CardTitle>Appearance</CardTitle>
              <CardDescription>
                The widget loads these when it starts, so a change reaches every site it is embedded
                on without anyone editing the snippet.
              </CardDescription>
            </div>
          </CardHeader>

          <CardContent>
            <FieldGroup>
              {state.status === 'error' && state.message ? (
                <Alert variant="destructive" role="status" className="no-js-only">
                  <AlertDescription>{state.message}</AlertDescription>
                </Alert>
              ) : null}

              <FieldSet>
                <FieldLegend variant="label">Brand</FieldLegend>
                <FieldGroup className="grid gap-4 sm:grid-cols-2">
                  {BRAND_COLOURS.map((colour) => (
                    <ColourField
                      key={colour.name}
                      control={form.control}
                      name={colour.name}
                      label={colour.label}
                      description={colour.description}
                    />
                  ))}
                </FieldGroup>
              </FieldSet>

              <FieldSet>
                <FieldLegend variant="label">Panel</FieldLegend>
                <FieldGroup className="grid gap-4 sm:grid-cols-2">
                  {PANEL_COLOURS.map((colour) => (
                    <ColourField
                      key={colour.name}
                      control={form.control}
                      name={colour.name}
                      label={colour.label}
                      description={colour.description}
                    />
                  ))}
                </FieldGroup>
              </FieldSet>

              <FieldSet>
                <FieldLegend variant="label">Layout</FieldLegend>
                <FieldGroup className="grid gap-4 sm:grid-cols-3">
                  <FormField
                    control={form.control}
                    name="radius"
                    label="Corner radius"
                    description="0 for square corners."
                  >
                    {({ field, invalid }) => (
                      <Input
                        {...field}
                        id={field.name}
                        type="number"
                        min={0}
                        max={28}
                        aria-invalid={invalid}
                      />
                    )}
                  </FormField>

                  <FormField
                    control={form.control}
                    name="position"
                    label="Launcher position"
                    description="Which corner of the page it sits in."
                  >
                    {({ field, invalid }) => (
                      <NativeSelect {...field} id={field.name} aria-invalid={invalid}>
                        <option value="right">Bottom right</option>
                        <option value="left">Bottom left</option>
                      </NativeSelect>
                    )}
                  </FormField>

                  <FormField
                    control={form.control}
                    name="scheme"
                    label="Colour scheme"
                    description={SCHEME_HINT[String(values.scheme)]}
                  >
                    {({ field, invalid }) => (
                      <NativeSelect {...field} id={field.name} aria-invalid={invalid}>
                        <option value="system">Follow the visitor</option>
                        <option value="light">Light</option>
                        <option value="dark">Dark</option>
                      </NativeSelect>
                    )}
                  </FormField>
                </FieldGroup>
              </FieldSet>

              <FieldSet>
                <FieldLegend variant="label">Wording</FieldLegend>
                <FieldGroup>
                  <FormField
                    control={form.control}
                    name="title"
                    label="Header"
                    description={`Leave this empty to use the chatbot's name, “${chatbot.name}”.`}
                  >
                    {({ field, invalid }) => (
                      <Input
                        {...field}
                        id={field.name}
                        maxLength={60}
                        placeholder={chatbot.name}
                        aria-invalid={invalid}
                      />
                    )}
                  </FormField>

                  <FormField
                    control={form.control}
                    name="greeting"
                    label="Opening message"
                    description="The first thing a visitor sees. Empty means the generated one."
                  >
                    {({ field, invalid }) => (
                      <Input
                        {...field}
                        id={field.name}
                        maxLength={300}
                        placeholder={`Hi! Ask me anything and I'll answer from ${chatbot.name}'s documents.`}
                        aria-invalid={invalid}
                      />
                    )}
                  </FormField>
                </FieldGroup>
              </FieldSet>

              <FieldSet>
                <FieldLegend variant="label">Footer links</FieldLegend>
                <FieldDescription>
                  Shown in the widget footer, above the branding. Leave one empty and it is not
                  shown. These are kept when you reset the theme.
                </FieldDescription>
                <FieldGroup className="grid gap-4 sm:grid-cols-2">
                  <FormField
                    control={form.control}
                    name="privacy_url"
                    label="Privacy policy"
                    description="The full address, including https://."
                  >
                    {({ field, invalid }) => (
                      <Input
                        {...field}
                        id={field.name}
                        type="url"
                        inputMode="url"
                        maxLength={500}
                        spellCheck={false}
                        placeholder="https://example.com/privacy"
                        aria-invalid={invalid}
                      />
                    )}
                  </FormField>

                  <FormField
                    control={form.control}
                    name="terms_url"
                    label="Terms"
                    description="The full address, including https://."
                  >
                    {({ field, invalid }) => (
                      <Input
                        {...field}
                        id={field.name}
                        type="url"
                        inputMode="url"
                        maxLength={500}
                        spellCheck={false}
                        placeholder="https://example.com/terms"
                        aria-invalid={invalid}
                      />
                    )}
                  </FormField>
                </FieldGroup>
              </FieldSet>
            </FieldGroup>
          </CardContent>

          <CardFooter>
            <SubmitButton pendingLabel="Saving…">Save appearance</SubmitButton>
          </CardFooter>
        </Card>
      </form>

      <Card className="lg:sticky lg:top-6">
        <CardHeader>
          <div className="space-y-1">
            <CardTitle>Preview</CardTitle>
            <CardDescription>
              Updates as you type. The real widget renders at the size of its own frame.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <WidgetPreview
            theme={values}
            name={values.title || chatbot.name}
            greeting={
              values.greeting ||
              `Hi! Ask me anything and I'll answer from ${chatbot.name}'s documents.`
            }
          />
          <Field>
            <FieldDescription>
              Setting a colour pins it: a widget whose palette is fully specified looks the same for
              every visitor, whichever scheme their device asks for. Resetting hands all of that
              back to the widget.
            </FieldDescription>
          </Field>
        </CardContent>
        <CardFooter>
          {/* Its own form, not a second button in the one above: a reset has nothing to
              validate, and sharing that form would let an unfinished colour block the way
              back to the default. */}
          <form action={resetAction}>
            <input type="hidden" name="chatbot_id" value={chatbot.id} />
            {/* Not `name="reset"`: a form's named controls shadow its own properties, so that
                one replaces `form.reset` with an input element and everything that calls the
                method — React's own post-action reset included — throws. */}
            <input type="hidden" name="intent" value="reset" />
            <ConfirmSubmit
              variant="ghost"
              size="sm"
              confirmTitle="Reset to the default theme?"
              confirmDescription="The colours saved here are discarded and the widget goes back to its own palette, which follows each visitor's light or dark setting."
              confirmLabel="Reset"
            >
              Reset to the default theme
            </ConfirmSubmit>
          </form>
        </CardFooter>
      </Card>
    </div>
  )
}

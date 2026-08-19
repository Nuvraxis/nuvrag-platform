'use client'

import { Field, FieldDescription, FieldError, FieldLabel, Input } from '@rag/ui'
import type { ReactNode } from 'react'
import { Controller, type Control, type FieldValues, type Path } from 'react-hook-form'

const HEX = /^#[0-9a-fA-F]{6}$/

export interface ColourFieldProps<Values extends FieldValues> {
  control: Control<Values>
  name: Path<Values>
  label: ReactNode
  description?: ReactNode
}

/**
 * A colour, editable as a swatch or as text.
 *
 * Both controls drive the same value, because neither alone is enough: the native picker is
 * how someone chooses a colour they have not decided on, and the text box is how someone
 * pastes the hex their brand guidelines already specify. Only the text box carries the
 * field's `name`, so the form submits one value per colour whether or not scripts ran — the
 * picker is a convenience layered on top of an input that works without it.
 */
export function ColourField<Values extends FieldValues>({
  control,
  name,
  label,
  description,
}: ColourFieldProps<Values>) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => {
        const value = typeof field.value === 'string' ? field.value : ''
        return (
          <Field data-invalid={fieldState.invalid || undefined}>
            <FieldLabel htmlFor={field.name}>{label}</FieldLabel>
            <div className="flex items-center gap-2">
              <input
                type="color"
                aria-label={`${typeof label === 'string' ? label : field.name} colour picker`}
                tabIndex={-1}
                // A partly-typed hex would reset the native control to black, so it follows
                // the text box only once there is a colour to follow.
                value={HEX.test(value) ? value : '#000000'}
                onChange={(event) => field.onChange(event.target.value)}
                className="border-input size-9 shrink-0 cursor-pointer rounded-md border bg-transparent p-1"
              />
              <Input
                {...field}
                id={field.name}
                value={value}
                spellCheck={false}
                autoComplete="off"
                maxLength={7}
                aria-invalid={fieldState.invalid}
                className="font-mono text-xs uppercase"
              />
            </div>
            {description ? <FieldDescription>{description}</FieldDescription> : null}
            <FieldError errors={[fieldState.error]} />
          </Field>
        )
      }}
    />
  )
}

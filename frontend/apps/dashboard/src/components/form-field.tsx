'use client'

import { Field, FieldDescription, FieldError, FieldLabel } from '@rag/ui'
import type { ComponentProps, ReactNode } from 'react'
import {
  Controller,
  type Control,
  type ControllerRenderProps,
  type FieldValues,
  type Path,
} from 'react-hook-form'

export interface FormFieldProps<Values extends FieldValues, Name extends Path<Values>> {
  control: Control<Values>
  name: Name
  label: ReactNode
  /** Stays visible while an error is showing: it is usually what explains the error. */
  description?: ReactNode
  className?: string
  orientation?: ComponentProps<typeof Field>['orientation']
  children: (props: { field: ControllerRenderProps<Values, Name>; invalid: boolean }) => ReactNode
}

/**
 * The anatomy shadcn documents for React Hook Form — `Controller` around `Field`, with the
 * label, control and message as one unit — written once instead of at every input.
 *
 * The control comes in as a render prop rather than being cloned, so a field keeps whatever
 * type, autocomplete and placeholder it needs while the surrounding markup stays identical.
 */
export function FormField<Values extends FieldValues, Name extends Path<Values>>({
  control,
  name,
  label,
  description,
  className,
  orientation,
  children,
}: FormFieldProps<Values, Name>) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Field
          className={className}
          orientation={orientation}
          data-invalid={fieldState.invalid || undefined}
        >
          <FieldLabel htmlFor={field.name}>{label}</FieldLabel>
          {children({ field, invalid: fieldState.invalid })}
          {description ? <FieldDescription>{description}</FieldDescription> : null}
          <FieldError errors={[fieldState.error]} />
        </Field>
      )}
    />
  )
}

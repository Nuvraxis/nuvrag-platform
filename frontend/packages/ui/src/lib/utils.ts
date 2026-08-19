import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Joins class names and lets a caller's utility win over the component's default. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

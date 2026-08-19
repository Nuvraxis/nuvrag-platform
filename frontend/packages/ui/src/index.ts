// `components/ui` is vendored shadcn/ui — regenerate it with `pnpm dlx shadcn@latest add
// <name>` from this package, which `components.json` points at. Everything beside it is ours.

export { Alert, AlertDescription, AlertTitle } from './components/ui/alert'
export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogTitle,
  AlertDialogTrigger,
} from './components/ui/alert-dialog'
export { Badge, badgeVariants } from './components/ui/badge'
export { Button, buttonVariants } from './components/ui/button'
export {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from './components/ui/card'
export {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSeparator,
  FieldSet,
  FieldTitle,
} from './components/ui/field'
export { Input } from './components/ui/input'
export { Label } from './components/ui/label'
export { Separator } from './components/ui/separator'
export { Toaster } from './components/ui/sonner'
// Re-exported so callers reach for one package rather than depending on sonner directly.
export { toast } from 'sonner'
export {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from './components/ui/table'
export { Textarea } from './components/ui/textarea'

export { EmptyState, Spinner } from './components/empty-state'
export type { EmptyStateProps } from './components/empty-state'
export { NativeSelect } from './components/native-select'
export { Stat } from './components/stat'
export type { StatProps } from './components/stat'

export { cn } from './lib/utils'

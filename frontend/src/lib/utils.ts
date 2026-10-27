import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
export function formatCurrency(value: number, currency: string = "TND") {
  return new Intl.NumberFormat("fr-TN", { style: "currency", currency, maximumFractionDigits: 2 }).format(value || 0)
}
export function formatDate(date: string | Date | null | undefined) {
  if (!date) return "-"
  return new Date(date).toLocaleDateString("fr-TN")
}
export function formatDateTime(date: string | Date | null | undefined) {
  if (!date) return "-"
  return new Date(date).toLocaleString("fr-TN")
}

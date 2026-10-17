import { ThemeProvider as NextThemesProvider } from "next-themes"
import type { ComponentProps } from "react"

/**
 * Thin wrapper around next-themes. It is not Next-specific: it works in any
 * React app and toggles the `.dark` class on <html>, which is exactly what the
 * shadcn Tailwind v4 tokens in `src/index.css` are keyed off.
 */
export function ThemeProvider({
  children,
  ...props
}: ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  )
}

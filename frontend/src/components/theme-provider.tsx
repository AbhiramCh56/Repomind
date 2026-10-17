import { ThemeProvider as NextThemesProvider } from "next-themes"
import type { ComponentProps } from "react"

/**
 * next-themes is not Next-specific: it works in any React app and toggles the
 * `.dark` class on <html>, which is what the shadcn Tailwind v4 tokens in
 * `src/index.css` are keyed off.
 *
 * The app is dark-only for now, so the theme is *forced* rather than merely
 * defaulted: a stale `theme` value left in localStorage by an earlier build
 * cannot flip the UI back to light. Setting `defaultTheme` as well keeps
 * `useTheme().resolvedTheme` reporting "dark" (the diagram renderers read it).
 */
export function ThemeProvider({
  children,
  ...props
}: ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="dark"
      forcedTheme="dark"
      enableSystem={false}
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  )
}

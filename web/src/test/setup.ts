import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

// BUG-006: the default 1 s for findBy/waitFor is too short on a loaded laptop or a CI runner.
// Keep it below Vitest's testTimeout (vite.config.ts) so a miss reports the missing element.
configure({ asyncUtilTimeout: 5000 })

afterEach(() => {
  cleanup()
})

// jsdom gaps used by the app.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }) as MediaQueryList
}
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || function () {}

import axe from 'axe-core'

/** Serious or critical axe violations in `root` (colour contrast needs real layout; checked in the browser). */
export async function seriousViolations(root: Element = document.body) {
  const result = await axe.run(root, {
    rules: { 'color-contrast': { enabled: false } },
    resultTypes: ['violations'],
  })
  return result.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(', ')})`)
}

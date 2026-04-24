/**
 * Tabs — Sovereign Interface primitive
 *
 * Controlled tab navigation for admin panels and multi-view layouts.
 * Container: bg-surface-container-low rounded.
 * Active tab: bg-surface-container-highest text-on-surface font-semibold.
 * Inactive tab: transparent text-on-surface-variant, hover:text-on-surface.
 * Pills PROHIBITED — rounded or rounded-sm only.
 * Uses data-active="true" on the active tab for testing.
 */

export interface TabItem {
  key: string
  label: string
}

export interface TabsProps {
  tabs: TabItem[]
  activeKey: string
  onTabChange: (key: string) => void
  className?: string
}

export function Tabs({ tabs, activeKey, onTabChange, className = '' }: TabsProps) {
  return (
    <div
      data-component="tabs"
      role="tablist"
      className={[
        'flex',
        'bg-surface-container-low',
        'rounded',
        'p-1',
        'gap-1',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {tabs.map((tab) => {
        const isActive = tab.key === activeKey
        return (
          <button
            key={tab.key}
            role="tab"
            aria-selected={isActive}
            data-active={isActive ? 'true' : 'false'}
            data-tab-key={tab.key}
            onClick={() => onTabChange(tab.key)}
            className={[
              'px-4 py-2',
              'text-sm',
              'rounded-sm',
              'transition-all duration-150',
              'focus:outline-none',
              isActive
                ? 'bg-surface-container-highest text-on-surface font-semibold'
                : 'bg-transparent text-on-surface-variant hover:text-on-surface',
            ]
              .filter(Boolean)
              .join(' ')}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

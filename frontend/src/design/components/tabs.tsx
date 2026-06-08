/**
 * Tabs — Qora Design System primitive
 *
 * Controlled tab navigation for admin panels and multi-view layouts.
 * Container: bg-mist rounded-md.
 * Active tab: bg-paper text-ink font-semibold.
 * Inactive tab: transparent text-ink-2, hover:text-ink.
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
        'bg-mist',
        'rounded-md',
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
              'rounded-md',
              'transition-all duration-150',
              'focus:outline-none',
              isActive
                ? 'bg-paper text-ink font-semibold shadow-sm'
                : 'bg-transparent text-ink-2 hover:text-ink',
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

/**
 * Tabs Component Tests
 * TDD Layer: Integration — render + behavioral assertions
 */

import { render, screen } from '@testing-library/react'
import { userEvent } from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Tabs } from './tabs'

const sampleTabs = [
  { key: 'clients', label: 'Clients' },
  { key: 'agents', label: 'Agents' },
]

describe('Tabs — rendering', () => {
  it('renders all tab labels', () => {
    render(<Tabs tabs={sampleTabs} activeKey="clients" onTabChange={vi.fn()} />)
    expect(screen.getByText('Clients')).toBeInTheDocument()
    expect(screen.getByText('Agents')).toBeInTheDocument()
  })

  it('renders a tablist container', () => {
    render(<Tabs tabs={sampleTabs} activeKey="clients" onTabChange={vi.fn()} />)
    expect(screen.getByRole('tablist')).toBeInTheDocument()
  })

  it('renders tab buttons with role=tab', () => {
    render(<Tabs tabs={sampleTabs} activeKey="clients" onTabChange={vi.fn()} />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(2)
  })
})

describe('Tabs — active state', () => {
  it('active tab has data-active="true"', () => {
    render(<Tabs tabs={sampleTabs} activeKey="clients" onTabChange={vi.fn()} />)
    const clientsTab = screen.getByRole('tab', { name: 'Clients' })
    expect(clientsTab).toHaveAttribute('data-active', 'true')
  })

  it('inactive tab has data-active="false"', () => {
    render(<Tabs tabs={sampleTabs} activeKey="clients" onTabChange={vi.fn()} />)
    const agentsTab = screen.getByRole('tab', { name: 'Agents' })
    expect(agentsTab).toHaveAttribute('data-active', 'false')
  })

  it('active tab has aria-selected="true"', () => {
    render(<Tabs tabs={sampleTabs} activeKey="agents" onTabChange={vi.fn()} />)
    const agentsTab = screen.getByRole('tab', { name: 'Agents' })
    expect(agentsTab).toHaveAttribute('aria-selected', 'true')
  })

  it('inactive tab has aria-selected="false"', () => {
    render(<Tabs tabs={sampleTabs} activeKey="agents" onTabChange={vi.fn()} />)
    const clientsTab = screen.getByRole('tab', { name: 'Clients' })
    expect(clientsTab).toHaveAttribute('aria-selected', 'false')
  })
})

describe('Tabs — tab switching', () => {
  it('calls onTabChange with correct key when tab is clicked', async () => {
    const user = userEvent.setup()
    const onTabChange = vi.fn()
    render(<Tabs tabs={sampleTabs} activeKey="clients" onTabChange={onTabChange} />)
    await user.click(screen.getByRole('tab', { name: 'Agents' }))
    expect(onTabChange).toHaveBeenCalledWith('agents')
  })

  it('calls onTabChange once per click', async () => {
    const user = userEvent.setup()
    const onTabChange = vi.fn()
    render(<Tabs tabs={sampleTabs} activeKey="clients" onTabChange={onTabChange} />)
    await user.click(screen.getByRole('tab', { name: 'Agents' }))
    expect(onTabChange).toHaveBeenCalledTimes(1)
  })
})

describe('Tabs — controlled mode', () => {
  it('reflects activeKey changes when rerendered', () => {
    const { rerender } = render(
      <Tabs tabs={sampleTabs} activeKey="clients" onTabChange={vi.fn()} />
    )
    expect(screen.getByRole('tab', { name: 'Clients' })).toHaveAttribute('data-active', 'true')

    rerender(<Tabs tabs={sampleTabs} activeKey="agents" onTabChange={vi.fn()} />)
    expect(screen.getByRole('tab', { name: 'Agents' })).toHaveAttribute('data-active', 'true')
    expect(screen.getByRole('tab', { name: 'Clients' })).toHaveAttribute('data-active', 'false')
  })
})

describe('Tabs — className passthrough', () => {
  it('applies additional className to container', () => {
    render(<Tabs tabs={sampleTabs} activeKey="clients" onTabChange={vi.fn()} className="custom-tabs" />)
    expect(screen.getByRole('tablist')).toHaveClass('custom-tabs')
  })
})

describe('Tabs — data-tab-key attribute', () => {
  it('each tab button has data-tab-key with its key', () => {
    render(<Tabs tabs={sampleTabs} activeKey="clients" onTabChange={vi.fn()} />)
    expect(screen.getByRole('tab', { name: 'Clients' })).toHaveAttribute('data-tab-key', 'clients')
    expect(screen.getByRole('tab', { name: 'Agents' })).toHaveAttribute('data-tab-key', 'agents')
  })
})

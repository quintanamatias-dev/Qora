import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { Icon } from './icon'

describe('Icon', () => {
  it('renders an svg with the given size', () => {
    render(<Icon name="grid" size={24} />)
    const svg = screen.getByRole('img', { hidden: true })
    expect(svg).toHaveAttribute('width', '24')
    expect(svg).toHaveAttribute('height', '24')
  })

  it('defaults to size 18', () => {
    render(<Icon name="search" />)
    const svg = screen.getByRole('img', { hidden: true })
    expect(svg).toHaveAttribute('width', '18')
    expect(svg).toHaveAttribute('height', '18')
  })

  it('renders distinct markup per icon name', () => {
    const { container: gridContainer } = render(<Icon name="grid" />)
    const { container: usersContainer } = render(<Icon name="users" />)
    expect(gridContainer.querySelector('svg')?.innerHTML).not.toBe(
      usersContainer.querySelector('svg')?.innerHTML,
    )
  })
})

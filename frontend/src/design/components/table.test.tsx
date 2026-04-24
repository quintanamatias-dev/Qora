/**
 * Table Component Tests
 * TDD Layer: Integration — render + behavioral assertions
 */

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from './table'

describe('Table — rendering', () => {
  it('renders a table element', () => {
    render(
      <Table>
        <TableBody>
          <TableRow>
            <TableCell>Content</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    )
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('has data-component="table" attribute', () => {
    render(<Table><TableBody><TableRow><TableCell>x</TableCell></TableRow></TableBody></Table>)
    expect(screen.getByRole('table')).toHaveAttribute('data-component', 'table')
  })

  it('applies additional className', () => {
    render(<Table className="custom-table"><TableBody><TableRow><TableCell>x</TableCell></TableRow></TableBody></Table>)
    expect(screen.getByRole('table')).toHaveClass('custom-table')
  })
})

describe('TableHeader — rendering', () => {
  it('renders a thead element with data-component', () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow><TableCell>x</TableCell></TableRow>
        </TableBody>
      </Table>
    )
    const thead = screen.getAllByRole('rowgroup')[0]
    expect(thead.tagName).toBe('THEAD')
    expect(thead).toHaveAttribute('data-component', 'table-header')
  })
})

describe('TableHead — rendering', () => {
  it('renders column header text', () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow><TableCell>x</TableCell><TableCell>y</TableCell></TableRow>
        </TableBody>
      </Table>
    )
    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('Status')).toBeInTheDocument()
  })

  it('has data-component="table-head" attribute', () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Col</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow><TableCell>x</TableCell></TableRow>
        </TableBody>
      </Table>
    )
    expect(screen.getByRole('columnheader', { name: 'Col' })).toHaveAttribute('data-component', 'table-head')
  })
})

describe('TableBody — rendering', () => {
  it('renders a tbody element with data-component', () => {
    render(
      <Table>
        <TableBody>
          <TableRow><TableCell>x</TableCell></TableRow>
        </TableBody>
      </Table>
    )
    const tbody = screen.getByRole('rowgroup')
    expect(tbody.tagName).toBe('TBODY')
    expect(tbody).toHaveAttribute('data-component', 'table-body')
  })
})

describe('TableRow — rendering', () => {
  it('renders row content', () => {
    render(
      <Table>
        <TableBody>
          <TableRow>
            <TableCell>Row content</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    )
    expect(screen.getByText('Row content')).toBeInTheDocument()
  })

  it('has data-component="table-row" attribute', () => {
    render(
      <Table>
        <TableBody>
          <TableRow>
            <TableCell>x</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    )
    expect(screen.getByRole('row')).toHaveAttribute('data-component', 'table-row')
  })
})

describe('TableCell — rendering', () => {
  it('renders cell content', () => {
    render(
      <Table>
        <TableBody>
          <TableRow>
            <TableCell>Cell value</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    )
    expect(screen.getByText('Cell value')).toBeInTheDocument()
  })

  it('has data-component="table-cell" attribute', () => {
    render(
      <Table>
        <TableBody>
          <TableRow>
            <TableCell>x</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    )
    expect(screen.getByRole('cell')).toHaveAttribute('data-component', 'table-cell')
  })

  it('applies additional className', () => {
    render(
      <Table>
        <TableBody>
          <TableRow>
            <TableCell className="highlight">data</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    )
    expect(screen.getByRole('cell')).toHaveClass('highlight')
  })
})

describe('Table — compound usage', () => {
  it('renders a full table with header and multiple rows', () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Email</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>Alice</TableCell>
            <TableCell>alice@test.com</TableCell>
          </TableRow>
          <TableRow>
            <TableCell>Bob</TableCell>
            <TableCell>bob@test.com</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    )
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('bob@test.com')).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(3) // 1 header + 2 body rows
  })
})

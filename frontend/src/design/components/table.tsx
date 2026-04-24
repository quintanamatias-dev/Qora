/**
 * Table — Sovereign Interface primitive
 *
 * Compound component providing: Table, TableHeader, TableBody, TableRow, TableHead, TableCell.
 * No outer border — uses background-shift elevation.
 * Header: text-xs uppercase tracking-wider text-on-surface-variant.
 * Rows: ghost separator (border-b-outline-variant/10, almost invisible).
 * Last row: no bottom separator.
 * Hover: bg-surface-container/50.
 */

import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react'

export interface TableProps extends HTMLAttributes<HTMLTableElement> {}
export interface TableHeaderProps extends HTMLAttributes<HTMLTableSectionElement> {}
export interface TableBodyProps extends HTMLAttributes<HTMLTableSectionElement> {}
export interface TableRowProps extends HTMLAttributes<HTMLTableRowElement> {}
export interface TableHeadProps extends ThHTMLAttributes<HTMLTableCellElement> {}
export interface TableCellProps extends TdHTMLAttributes<HTMLTableCellElement> {}

export function Table({ className = '', children, ...rest }: TableProps) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        data-component="table"
        className={[
          'w-full',
          'text-sm',
          'text-on-surface',
          'border-separate border-spacing-0',
          className,
        ]
          .filter(Boolean)
          .join(' ')}
        {...rest}
      >
        {children}
      </table>
    </div>
  )
}

export function TableHeader({ className = '', children, ...rest }: TableHeaderProps) {
  return (
    <thead
      data-component="table-header"
      className={['', className].filter(Boolean).join(' ')}
      {...rest}
    >
      {children}
    </thead>
  )
}

export function TableBody({ className = '', children, ...rest }: TableBodyProps) {
  return (
    <tbody
      data-component="table-body"
      className={['', className].filter(Boolean).join(' ')}
      {...rest}
    >
      {children}
    </tbody>
  )
}

export function TableRow({ className = '', children, ...rest }: TableRowProps) {
  return (
    <tr
      data-component="table-row"
      className={[
        'border-b border-b-outline-variant/10',
        'last:border-b-0',
        'hover:bg-surface-container/50',
        'transition-colors duration-100',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {children}
    </tr>
  )
}

export function TableHead({ className = '', children, ...rest }: TableHeadProps) {
  return (
    <th
      data-component="table-head"
      className={[
        'px-4 py-3',
        'text-xs font-medium uppercase tracking-wider',
        'text-on-surface-variant',
        'text-left',
        'bg-surface-container-low',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {children}
    </th>
  )
}

export function TableCell({ className = '', children, ...rest }: TableCellProps) {
  return (
    <td
      data-component="table-cell"
      className={[
        'px-4 py-3',
        'text-sm',
        'text-on-surface',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    >
      {children}
    </td>
  )
}

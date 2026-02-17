// src/components/Typography.jsx
import React from 'react';
import { THEME } from '../theme'; // Adjust path if needed

export const Header = ({ children }) => (
  <span style={{
    fontSize: THEME.fontSize.header,
    color: THEME.colors.textSecondary,
    fontFamily: 'sans-serif',
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    display: 'block'
  }}>
    {children}
  </span>
);

export const Label = ({ children }) => (
  <span style={{
    fontSize: THEME.fontSize.label,
    color: THEME.colors.textSecondary,
    fontFamily: 'sans-serif',
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    display: 'block'
  }}>
    {children}
  </span>
);

export const Value = ({ children, color = THEME.colors.textPrimary }) => (
  <span style={{
    fontSize: THEME.fontSize.value,
    fontFamily: THEME.fontFamily,
    fontWeight: '700',
    color: color,
    display: 'block'
  }}>
    {children}
  </span>
);
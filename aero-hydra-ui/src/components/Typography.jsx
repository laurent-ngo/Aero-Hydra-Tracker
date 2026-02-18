// src/components/Typography.jsx
import React from 'react';
import { THEME } from '../theme';

// Helper to get colors based on mode
const getModeColors = (mode) => THEME.modes[mode] || THEME.modes.light;

export const Header = ({ children, mode = 'dark' }) => {
  const colors = getModeColors(mode);
  return (
    <span style={{
      fontSize: THEME.fontSize.header,
      color: colors.accent, // Using accent for Headers often looks sharper
      fontFamily: 'sans-serif',
      fontWeight: '800',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      display: 'block'
    }}>
      {children}
    </span>
  );
};

export const Label = ({ children, mode = 'dark' }) => {
  const colors = getModeColors(mode);
  return (
    <span style={{
      fontSize: THEME.fontSize.label,
      color: colors.textSecondary,
      fontFamily: 'sans-serif',
      fontWeight: '800',
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      display: 'block'
    }}>
      {children}
    </span>
  );
};

export const Value = ({ children, mode = 'dark' }) => {
  const colors = getModeColors(mode);
  return (
    <span style={{
      fontSize: THEME.fontSize.value,
      fontFamily: THEME.fontFamily,
      fontWeight: '700',
      color: colors.textPrimary,
      display: 'block'
    }}>
      {children}
    </span>
  );
};
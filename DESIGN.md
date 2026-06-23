# Design

## Theme

Dark mode default with light mode support. Deep navy/black background with subtle borders. Data visualization uses a restricted palette of emerald, blue, purple, and amber accents against dark surfaces.

## Color Palette

### Backgrounds
- `--bg-primary`: #0B0F19 (main page background)
- `--bg-card`: #111827 (card surfaces)
- `--bg-elevated`: #1E293B (elevated surfaces, borders)

### Text
- `--text-primary`: #FFFFFF (headings, primary data)
- `--text-secondary`: #9CA3AF (labels, metadata)
- `--text-muted`: #6B7280 (placeholders, disabled)

### Accents
- `--accent-emerald`: #10B981 (positive, success, long)
- `--accent-blue`: #3B82F6 (info, neutral)
- `--accent-purple`: #8B5CF6 (strong signals, premium)
- `--accent-amber`: #F59E0B (warning, standard signals)
- `--accent-rose`: #EF4444 (negative, loss, short)

### Borders
- `--border-default`: #1E293B (subtle card borders)
- `--border-hover`: #334155 (hover state borders)

## Typography

- **Font Family**: System sans-serif stack (Inter, -apple-system, BlinkMacSystemFont)
- **Headings**: Bold, tight tracking
- **Data/Numbers**: Monospace for metrics and prices
- **Labels**: Small caps, muted color

## Components

### Metric Cards
- Dark card background (#111827)
- Colored circular icon top-left
- Info icon button top-right
- Metric label below icon
- Large bold number (text-3xl)
- Green/red change badge with arrow
- Subtle sparkline at bottom
- Equal height in 4-column grid

### Tables
- Dark header with subtle border
- Alternating row hover states
- Status badges with color coding
- Monospace for numeric columns

### Charts
- Line charts: emerald stroke, subtle gradient fill
- Pie charts: restricted palette (emerald, blue, amber, rose)
- Bar charts: emerald for positive, rose for negative
- Tooltips: dark background with border

## Layout

- Fixed sidebar (280px) with navigation
- Main content area with padding
- Grid-based responsive layouts
- Cards with consistent border radius (2xl)

## Theme Support

The dashboard supports both light and dark modes via `next-themes`:
- Default: Dark mode
- Toggle: Available in sidebar
- Persisted: Theme preference saved in localStorage
- CSS variables: Uses `var(--chart-1)`, `var(--chart-4)`, etc. for chart colors

# Design System Inspiration of Linear

## 1. Visual Theme & Atmosphere

Linear's website is a masterclass in dark-mode-first product design — a near-black canvas (`#08090a`) where content emerges from darkness like starlight. The overall impression is one of extreme precision engineering: every element exists in a carefully calibrated hierarchy of luminance, from barely-visible borders (`rgba(255,255,255,0.05)`) to soft, luminous text (`#f7f8f8`). This is not a dark theme applied to a light design — it is darkness as the native medium, where information density is managed through subtle gradations of white opacity rather than color variation.

The typography system is built entirely on Inter Variable with OpenType features `"cv01"` and `"ss03"` enabled globally, giving the typeface a cleaner, more geometric character. Inter is used at a remarkable range of weights — from 300 (light body) through 510 (medium, Linear's signature weight) to 590 (semibold emphasis). The 510 weight is particularly distinctive: it sits between regular and medium, creating a subtle emphasis that doesn't shout. At display sizes (72px, 64px, 48px), Inter uses aggressive negative letter-spacing (-1.584px to -1.056px), creating compressed, authoritative headlines that feel engineered rather than designed. Berkeley Mono serves as the monospace companion for code and technical labels, with fallbacks to ui-monospace, SF Mono, and Menlo.

The color system is almost entirely achromatic — dark backgrounds with white/gray text — punctuated by a single brand accent: Linear's signature indigo-violet (`#5e6ad2` for backgrounds, `#7170ff` for interactive accents). This accent color is used sparingly and intentionally, appearing only on CTAs, active states, and brand elements. The border system uses ultra-thin, semi-transparent white borders (`rgba(255,255,255,0.05)` to `rgba(255,255,255,0.08)`) that create structure without visual noise, like wireframes drawn in moonlight.

**Key Characteristics:**
- Dark-mode-native: `#08090a` marketing background, `#0f1011` panel background, `#191a1b` elevated surfaces
- Inter Variable with `"cv01", "ss03"` globally — geometric alternates for a cleaner aesthetic
- Signature weight 510 (between regular and medium) for most UI text
- Aggressive negative letter-spacing at display sizes (-1.584px at 72px, -1.056px at 48px)
- Brand indigo-violet: `#5e6ad2` (bg) / `#7170ff` (accent) / `#828fff` (hover) — the only chromatic color in the system
- Semi-transparent white borders throughout: `rgba(255,255,255,0.05)` to `rgba(255,255,255,0.08)`
- Button backgrounds at near-zero opacity: `rgba(255,255,255,0.02)` to `rgba(255,255,255,0.05)`
- Multi-layered shadows with inset variants for depth on dark surfaces
- Radix UI primitives as the component foundation
- Success green (`#27a644`, `#10b981`) used only for status indicators

## 2. Color Palette & Roles

### Background Surfaces
- **Marketing Black** (`#010102` / `#08090a`): The deepest background
- **Panel Dark** (`#0f1011`): Sidebar and panel backgrounds
- **Level 3 Surface** (`#191a1b`): Elevated surface areas, card backgrounds, dropdowns
- **Secondary Surface** (`#28282c`): Hover states and slightly elevated components

### Text & Content
- **Primary Text** (`#f7f8f8`): Near-white default text
- **Secondary Text** (`#d0d6e0`): Cool silver-gray for body text
- **Tertiary Text** (`#8a8f98`): Muted gray for placeholders/metadata
- **Quaternary Text** (`#62666d`): Timestamps, disabled states

### Brand & Accent
- **Brand Indigo** (`#5e6ad2`): CTA button backgrounds, brand marks
- **Accent Violet** (`#7170ff`): Links, active states, selected items
- **Accent Hover** (`#828fff`): Hover states on accent elements
- **Security Lavender** (`#7a7fad`): Security-related UI elements

### Status Colors
- **Green** (`#27a644`): Primary success/active status
- **Emerald** (`#10b981`): Secondary success — pill badges, completion states

### Border & Divider
- **Border Primary** (`#23252a`) / **Secondary** (`#34343a`) / **Tertiary** (`#3e3e44`)
- **Border Subtle** (`rgba(255,255,255,0.05)`): Ultra-subtle default
- **Border Standard** (`rgba(255,255,255,0.08)`): Cards, inputs, code blocks

## 3. Typography Rules

### Font Family
- **Primary**: `Inter Variable` (fallbacks: `SF Pro Display, -apple-system, system-ui`)
- **Monospace**: `Berkeley Mono` (fallbacks: `ui-monospace, SF Mono, Menlo`)
- **OpenType Features**: `"cv01", "ss03"` enabled globally

### Hierarchy (key levels)

| Role | Size | Weight | Line Height | Letter Spacing |
|------|------|--------|-------------|----------------|
| Display XL | 72px | 510 | 1.00 | -1.584px |
| Display Large | 64px | 510 | 1.00 | -1.408px |
| Display | 48px | 510 | 1.00 | -1.056px |
| Heading 1 | 32px | 400 | 1.13 | -0.704px |
| Heading 2 | 24px | 400 | 1.33 | -0.288px |
| Heading 3 | 20px | 590 | 1.33 | -0.24px |
| Body Large | 18px | 400 | 1.60 | -0.165px |
| Body | 16px | 400 | 1.50 | normal |
| Body Medium | 16px | 510 | 1.50 | normal |
| Small | 15px | 400 | 1.60 | -0.165px |
| Caption | 13px | 400–510 | 1.50 | -0.13px |
| Label | 12px | 400–590 | 1.40 | normal |
| Mono Body | 14px (Berkeley Mono) | 400 | 1.50 | normal |

## 4. Component Stylings

### Buttons
- **Ghost**: `rgba(255,255,255,0.02)` bg, `1px solid rgb(36,40,44)` border, 6px radius
- **Subtle**: `rgba(255,255,255,0.04)` bg, 6px radius
- **Primary Brand**: `#5e6ad2` bg, `#ffffff` text, 6px radius
- **Icon (Circle)**: `rgba(255,255,255,0.03)` bg, 50% radius, `1px solid rgba(255,255,255,0.08)` border
- **Pill**: transparent bg, 9999px radius, `1px solid rgb(35,37,42)` border
- **Small Toolbar**: `rgba(255,255,255,0.05)` bg, 2px radius, 12px/510 font

### Cards & Containers
- Background: `rgba(255,255,255,0.02)` to `rgba(255,255,255,0.05)` (always translucent)
- Border: `1px solid rgba(255,255,255,0.08)` standard
- Radius: 8px standard, 12px featured, 22px large panels

### Badges & Pills
- **Success Pill**: `#10b981` bg, 50% radius, 10px/510 font
- **Neutral Pill**: transparent, 9999px radius, `1px solid rgb(35,37,42)`
- **Subtle Badge**: `rgba(255,255,255,0.05)` bg, 2px radius, 10px/510 font

## 5. Layout Principles

### Spacing System
- Base unit: 8px
- Scale: 1px, 4px, 7px, 8px, 11px, 12px, 16px, 19px, 20px, 22px, 24px, 28px, 32px, 35px

### Border Radius Scale
- Micro (2px), Standard (4px), Comfortable (6px), Card (8px), Panel (12px), Large (22px), Pill (9999px), Circle (50%)

## 6. Depth & Elevation

| Level | Treatment |
|-------|-----------|
| Flat (0) | No shadow, `#010102` bg |
| Subtle (1) | `rgba(0,0,0,0.03) 0px 1.2px 0px` |
| Surface (2) | `rgba(255,255,255,0.05)` bg + `1px solid rgba(255,255,255,0.08)` |
| Inset (2b) | `rgba(0,0,0,0.2) 0px 0px 12px 0px inset` |
| Ring (3) | `rgba(0,0,0,0.2) 0px 0px 0px 1px` |
| Elevated (4) | `rgba(0,0,0,0.4) 0px 2px 4px` |
| Dialog (5) | Multi-layer shadow stack |

## 7. Do's and Don'ts

**Do:**
- Use Inter Variable with `"cv01", "ss03"` on ALL text
- Use weight 510 as your default emphasis weight
- Apply negative letter-spacing at display sizes
- Use `rgba(255,255,255,0.05–0.08)` for borders
- Keep button backgrounds nearly transparent
- Reserve brand indigo for CTAs only
- Use `#f7f8f8` for primary text, not pure white

**Don't:**
- Don't use pure `#ffffff` as primary text
- Don't use solid backgrounds for buttons
- Don't apply brand indigo decoratively
- Don't use positive letter-spacing on display text
- Don't use opaque borders on dark backgrounds
- Don't skip the OpenType features
- Don't use weight 700 — max is 590
- Don't introduce warm colors into the UI

## 8. Responsive Behavior

| Breakpoint | Width | Key Changes |
|------------|-------|-------------|
| Mobile Small | <600px | Single column |
| Mobile | 600–640px | Standard mobile |
| Tablet | 640–768px | Two-column grids begin |
| Desktop Small | 768–1024px | Full card grids |
| Desktop | 1024–1280px | Full navigation |
| Large Desktop | >1280px | Generous margins |

**Collapsing**: Hero 72px → 48px → 32px; nav collapses at 768px; cards 3→2→1 column; section spacing 80px+ → 48px mobile.

## 9. Agent Prompt Guide

**Quick Color Reference:**
- Page Background: `#08090a`, Panel: `#0f1011`, Surface: `#191a1b`
- Primary CTA: `#5e6ad2`, Accent: `#7170ff`, Hover: `#828fff`
- Heading: `#f7f8f8`, Body: `#d0d6e0`, Muted: `#8a8f98`, Subtle: `#62666d`
- Border default: `rgba(255,255,255,0.08)`, subtle: `rgba(255,255,255,0.05)`

**Example Prompts:**
- Hero: `#08090a` bg, 48px Inter 510 weight -1.056px tracking `#f7f8f8`, subtitle 18px/400 `#8a8f98`, CTA `#5e6ad2` 6px radius
- Card: `rgba(255,255,255,0.02)` bg, `1px solid rgba(255,255,255,0.08)` border, 8px radius, title 20px/590 -0.24px `#f7f8f8`
- Nav: `#0f1011` bg, 13px/510 `#d0d6e0` links, `#5e6ad2` CTA, `1px solid rgba(255,255,255,0.05)` bottom border

**Iteration Rules:**
1. Always set `font-feature-settings: "cv01", "ss03"` on all Inter text
2. Letter-spacing: -1.584px@72px, -1.056px@48px, -0.704px@32px, normal below 16px
3. Three weights: 400 (read), 510 (emphasize), 590 (announce)
4. Surface elevation via bg opacity: `rgba(255,255,255, 0.02→0.04→0.05)`
5. Brand indigo is the ONLY chromatic color
6. Borders always semi-transparent white, never solid dark on dark
7. Berkeley Mono for code, Inter Variable for everything else

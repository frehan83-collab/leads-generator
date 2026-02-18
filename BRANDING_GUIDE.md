# Sperton + ERA Branding Guide

## 🎨 Design System

### Color Palette

| Brand | Primary | Secondary | Accent | Usage |
|-------|---------|-----------|--------|-------|
| **Sperton** | #2563eb (Blue) | #3b82f6 | #1e40af | Recruitment features |
| **ERA** | #0F3460 (Navy) | #1F5A96 | #2E7D9A | Analytics features |
| **Neutral** | #0f172a (Dark) | #1e293b (Slate) | #64748b | Background & borders |

### Typography

- **Heading**: Bold, 24-32px
- **Subheading**: Semibold, 16-20px
- **Body**: Regular, 14px
- **Caption**: Small, 12px

### Spacing & Layout

- Sidebar width: 240px (w-60)
- Main content padding: 24px (px-6 py-6)
- Card padding: 20px (p-5)
- Gap between items: 16px (gap-4)

---

## 🏷️ Adding Official Logos

### **Sperton Logo**

**Where to get:**
1. Visit https://www.sperton.com/
2. Download their logo (SVG or PNG preferred)
3. Or find in their media kit

**How to integrate:**

```bash
# Create static directory if needed
mkdir -p C:\leads_generator\src\web\static\logos\

# Save Sperton logo
# C:\leads_generator\src\web\static\logos\sperton-logo.svg
```

**Update base.html:**

```html
<!-- Replace lines 32-41 in base.html -->
<div class="px-5 py-5 border-b border-slate-700">
    <div class="flex items-center gap-3 justify-between">
        <!-- Sperton Logo -->
        <img src="/static/logos/sperton-logo.svg"
             alt="Sperton"
             class="h-8 object-contain">

        <!-- Brand Toggle (optional) -->
        <button id="era-toggle" class="text-slate-400 hover:text-slate-200 transition">
            <img src="/static/logos/era-logo.svg"
                 alt="ERA"
                 class="h-6 object-contain opacity-60 hover:opacity-100">
        </button>
    </div>
</div>
```

### **ERA Group Logo**

**Where to get:**
1. Visit https://en.eragroup.com/
2. Download their official logo
3. Should be navy/blue color

**How to integrate:**

```bash
# Save ERA logo (same directory as Sperton)
# C:\leads_generator\src\web\static\logos\era-logo.svg
```

**Logo dimensions recommended:**
- Sperton: 160×40 pixels
- ERA: 140×40 pixels
- Format: SVG (scalable)

---

## 🎭 Visual Design Highlights

### Dashboard Layout

```
┌─────────────────────────────────────────┐
│  SIDEBAR (w-60)                         │
│  ┌─────────────────────────────────┐   │
│  │ [Sperton Logo]    [ERA Logo]    │   │
│  ├─────────────────────────────────┤   │
│  │ • Dashboard                     │   │
│  │ • Job Postings                  │   │
│  │ • Prospects                     │   │
│  │ • Campaigns                     │   │
│  │ • Settings                      │   │
│  │ ────────────────────────────    │   │
│  │ ERA GROUP                       │   │
│  │ • Analytics     [NEW!]          │   │
│  │ • Extractions   [NEW!]          │   │
│  │ • Templates     [NEW!]          │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

### Color Usage by Feature

**Sperton (Blue #2563eb):**
- Primary buttons
- Links & hover states
- Navigation active state
- Header row in exports

**ERA (Navy #0F3460):**
- Era dashboard background
- Excel export header
- Upload zone border
- Stat cards border

**Neutral (Slate #0f172a):**
- Main background
- Card backgrounds (#1e293b)
- Text on dark backgrounds

### Component Examples

#### Sperton Button (Primary)
```html
<button class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg">
    Create Campaign
</button>
```

#### ERA Button (Primary)
```html
<button class="bg-[#0F3460] hover:bg-[#1F5A96] text-white px-4 py-2 rounded-lg">
    Upload PDF
</button>
```

#### Stat Card
```html
<div class="bg-slate-800 border border-slate-700 rounded-xl p-5">
    <h3 class="text-xs font-semibold text-slate-400 uppercase">Metric Name</h3>
    <p class="text-2xl font-bold text-white mt-2">1,234</p>
    <p class="text-xs text-slate-500 mt-1">Description</p>
</div>
```

#### Badge Styles
```html
<!-- Sperton badges -->
<span class="badge-draft">Draft</span>
<span class="badge-approved">Approved</span>
<span class="badge-sent">Sent</span>

<!-- ERA badges -->
<span class="bg-purple-900/30 text-purple-300 px-3 py-1 rounded-full text-xs">
    📄 Invoice
</span>
<span class="bg-emerald-900/30 text-emerald-300 px-3 py-1 rounded-full text-xs">
    📊 Statement
</span>
```

---

## 📐 Responsive Design

### Desktop (1024px+)
- Sidebar: 240px fixed
- Main content: Flexible
- Grid layouts: 3-4 columns
- Tables: Full width with scroll

### Tablet (768px-1023px)
- Sidebar: 200px
- Grid layouts: 2 columns
- Tables: Horizontal scroll

### Mobile (< 768px)
- Sidebar: Collapse/hamburger menu
- Grid layouts: 1 column stacked
- Cards: Full width
- Touch-friendly buttons (44px min)

---

## 🎨 Custom CSS Classes

All defined in `base.html` `<style>` block:

```css
.sidebar-link              /* Nav items */
.sidebar-link.active       /* Active nav item */
.card                      /* Main content card */
.badge-draft               /* Status badge styles */
.badge-approved
.badge-sent
.badge-replied
.badge-valid
.badge-unknown
.badge-not_valid
.badge-running
.badge-completed
.badge-failed
```

---

## 🎬 UI Animations & Transitions

### Hover Effects
```css
transition-colors       /* Color changes on hover */
transition-all          /* All properties change smoothly */
hover:bg-slate-700      /* Background on hover */
hover:text-white        /* Text color on hover */
```

### Loading States
```html
<div id="upload-progress-bar" class="bg-blue-600 h-2 rounded-full"
     style="width: 0%"></div>
<!-- Width animates from 0-100% -->
```

### Status Indicators
```python
# Dashboard shows real-time status
pending    → ◇ (empty diamond)
processing → ◆ (filled diamond)
completed  → ✓ (checkmark - green)
error      → ✗ (X - red)
```

---

## 📊 Design Inspiration Sources

### Benchmarked Against:
- **Tableau** - Clean stat cards, professional dashboards
- **Power BI** - Data visualization, color schemes
- **Docparser** - PDF upload UX, progress indication
- **Klippa** - Extraction interface, confidence scoring

### Key Design Principles Applied:
1. **Clarity** - Information hierarchy is clear
2. **Consistency** - Colors and spacing throughout
3. **Feedback** - Users know status at all times
4. **Efficiency** - Common tasks require minimal clicks
5. **Accessibility** - Readable contrast, keyboard navigation

---

## 🎯 Brand Guidelines Compliance

### Sperton Brand Colors
✅ Primary blue used for CTA buttons
✅ White text on dark backgrounds
✅ Logo displayed in top-left
✅ Professional, recruitment-focused tone

### ERA Group Brand Integration
✅ Navy blue (#0F3460) for analytics section
✅ Professional, data-focused presentation
✅ Logo area reserved (top-right or toggle)
✅ Separate visual section in sidebar

---

## 📱 Mobile Responsiveness

### Dashboard (Mobile View)
```
┌──────────────────────────┐
│ ☰ Sperton Leads          │  (Hamburger menu)
├──────────────────────────┤
│ 📊 Uploads          [123]│
│ 📋 Extractions      [456]│
│ 🎯 Confidence       [89%]│
│ ⚡ Processing Time  [18s]│
├──────────────────────────┤
│ Upload PDF Here...       │  (Full width)
│ [Browse Files]           │
├──────────────────────────┤
│ Recent Uploads:          │
│ • invoice_1.pdf  ✓      │
│ • contract.pdf   ◆      │
└──────────────────────────┘
```

---

## 🌓 Dark Mode Support

Tailwind CSS dark mode is configured:

```html
<!-- In base.html -->
<html lang="no" class="dark">
  <!-- Uses dark mode by default -->
  <!-- All dark: classes are active -->
</html>
```

**Light Mode Support (Future):**
```html
<!-- Could be toggled with JavaScript -->
<button onclick="document.documentElement.classList.toggle('dark')">
    🌙 Toggle Theme
</button>
```

---

## 📝 Branding Checklist

- [ ] Sperton logo in sidebar (top-left)
- [ ] ERA logo displayed (top-right or toggle)
- [ ] Sperton blue (#2563eb) for recruitment features
- [ ] ERA navy (#0F3460) for analytics features
- [ ] Consistent card styling throughout
- [ ] Proper spacing and padding
- [ ] Dark theme applied globally
- [ ] Responsive design on mobile
- [ ] Status indicators visible
- [ ] Professional fonts and sizing
- [ ] Color contrast meets WCAG AA
- [ ] Hover states working smoothly

---

## 🔧 Customization Guide

### Change Primary Button Color
```css
/* Find in routes or templates */
<button class="bg-blue-600 hover:bg-blue-700">
/* Change to */
<button class="bg-emerald-600 hover:bg-emerald-700">
```

### Change Card Styling
```css
/* In base.html <style> */
.card { @apply bg-slate-800 border border-slate-700 rounded-xl p-5; }
/* Could change to */
.card { @apply bg-slate-750 border-2 border-slate-600 rounded-lg p-4; }
```

### Add Custom Font
```html
<!-- In base.html <head> -->
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
    body { font-family: 'Inter', sans-serif; }
</style>
```

---

## 🎨 Design System Tokens

```javascript
// Tailwind Configuration (if customizing)
colors: {
    sperton: '#2563eb',
    era: '#0F3460',
    slate: {
        900: '#0f172a',
        800: '#1e293b',
        700: '#334155',
        400: '#78909c',
        200: '#cbd5e1',
    }
}

spacing: {
    xs: '4px',
    sm: '8px',
    md: '16px',
    lg: '24px',
    xl: '32px',
}

fontSize: {
    xs: '12px',
    sm: '14px',
    base: '16px',
    lg: '18px',
    xl: '20px',
    '2xl': '24px',
}
```

---

## 📚 Resources

### Official Brand Kits
- **Sperton**: https://www.sperton.com/ (brand assets)
- **ERA Group**: https://en.eragroup.com/ (logos & guidelines)

### Design Tools Used
- **Tailwind CSS** - Utility-first CSS framework
- **Heroicons** - SVG icons in templates
- **Color.review** - Contrast checking

### Font Recommendations
- **Sans-serif**: Inter, Segoe UI, -apple-system
- **Monospace**: Monaco, Menlo (for code)

---

**Version:** 1.0
**Last Updated:** February 18, 2025
**Status:** Ready for Logo Integration 🎨

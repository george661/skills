---
name: mockups
description: Generate HTML mockups from PRP plans using frontend-app design system with light/dark themes and screenshots
agent-invokeable: true
---

# Mockups Skill

Generate standalone HTML mockups from PRP (Problem Requirements Plan) documents using the **exact** frontend-app design system and layout patterns. Creates both light and dark theme versions and captures screenshots using Chrome DevTools.

## Usage

```
/mockups <path-to-plan>
```

**Examples:**
```
/mockups project-docs/PRPs/MVP/PRP-RFI-001.md
/mockups project-docs/PRPs/1Q26/PRP-RFI-001B-marketplace-discovery.md
/mockups project-docs/PRPs/MVP/  (processes all PRPs in directory)
```

## Prerequisites

- Chrome DevTools MCP server must be available
- frontend-app repository must be accessible for design system reference

## CRITICAL: Reference frontend-app Before Creating Mockups

**Before generating any HTML, you MUST read the actual frontend-app source files:**

```typescript
// MANDATORY: Read these files first
await Read({ file_path: "${PROJECT_ROOT}/frontend-app/src/components/layouts/AppLayout.tsx" });
await Read({ file_path: "${PROJECT_ROOT}/frontend-app/src/components/navigation/Sidebar.tsx" });
await Read({ file_path: "${PROJECT_ROOT}/frontend-app/src/components/navigation/Header.tsx" });
await Read({ file_path: "${PROJECT_ROOT}/frontend-app/src/index.css" });  // globals.css / design tokens

// Read an example page to understand page structure patterns
await Read({ file_path: "${PROJECT_ROOT}/frontend-app/src/pages/organization/GeneralPage.tsx" });
```

This ensures mockups match the **current** application state, not outdated patterns.

---

## Phase 1: Analyze Plan Document

### 1.1 Read and Parse the Plan

```typescript
const planContent = await Read({ file_path: planPath });

// Extract mockup specifications from:
// - "## Mockup" or "## UI" sections
// - ASCII art diagrams
// - Component descriptions
// - User flow descriptions
// - Screen/view names
```

### 1.2 Identify Unique Views

| Pattern | Example | Extracts |
|---------|---------|----------|
| Section headers | `## Marketplace Tab`, `### Profile Page` | View names |
| ASCII mockups | `┌───────────────┐` | UI structure |
| Component lists | `- Header with navigation` | UI elements |
| User flows | `User clicks → navigates to` | Screen transitions |
| State variations | `(Pending)`, `(Accepted)`, `(Delivered)` | View states |

### 1.3 Create View Inventory

```javascript
const views = [
  {
    name: "view-name",
    filename: "view-name.html",
    description: "Description from plan",
    navSection: "marketplace" | "personal" | "organization" | "admin" | "developer",
    activeNavItem: "Applications" | "My Sessions" | etc,
    pageTitle: "Page Title",
    pageDescription: "Optional description",
  }
];
```

---

## Phase 2: Setup Output Directory

### 2.1 Create Directory Structure

```bash
mkdir -p ${TENANT_DOCS_PATH}/mockups/${feature}/light
mkdir -p ${TENANT_DOCS_PATH}/mockups/${feature}/dark
mkdir -p ${TENANT_DOCS_PATH}/mockups/${feature}/screenshots
```

### 2.2 Create Design System CSS

Copy the canonical design system from `project-docs/mockups/rfi/design-system.css` or generate from frontend-app's actual CSS variables.

---

## Phase 3: Generate HTML Views

### 3.1 MANDATORY: AppLayout Structure

**Every mockup MUST use the exact frontend-app AppLayout structure:**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>[Page Title] - the platform</title>
  <link rel="stylesheet" href="../design-system.css">
</head>
<body><!-- or <body class="dark"> for dark theme -->
  <div class="app-layout">
    <!-- SIDEBAR (64px collapsed, 256px expanded - show expanded for mockups) -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="logo">
          <span class="logo-icon">App</span>
          <span class="logo-text">the platform</span>
        </div>
      </div>

      <nav class="sidebar-nav">
        <!-- Navigation sections in EXACT order from frontend-app -->
        <!-- See Section 3.2 for navigation structure -->
      </nav>

      <div class="sidebar-footer">
        <button class="collapse-btn">
          <span class="icon">◀</span>
        </button>
      </div>
    </aside>

    <!-- MAIN AREA -->
    <div class="main-area">
      <!-- HEADER (fixed, 64px height) -->
      <header class="app-header">
        <div class="header-left">
          <button class="menu-btn mobile-only">☰</button>
        </div>
        <div class="header-right">
          <!-- Organization Switcher (if multiple orgs) -->
          <div class="org-switcher">
            <span class="org-name">Acme Corp</span>
            <span class="icon">▼</span>
          </div>
          <!-- Token Meter -->
          <div class="token-meter">
            <span class="token-icon">●</span>
            <span class="token-balance">1,250 SMART</span>
          </div>
          <!-- User Menu -->
          <div class="user-menu">
            <div class="avatar">JS</div>
          </div>
        </div>
      </header>

      <!-- PAGE CONTENT -->
      <main class="page-content">
        <!-- Page-specific content here -->
      </main>
    </div>
  </div>
</body>
</html>
```

### 3.2 MANDATORY: Sidebar Navigation Structure

The sidebar navigation MUST follow the **exact** section order from frontend-app:

```html
<nav class="sidebar-nav">
  <!-- SECTION 1: Marketplace (all authenticated users) -->
  <div class="nav-section">
    <div class="nav-section-title">Marketplace</div>
    <a href="#" class="nav-item">
      <span class="nav-icon">🏪</span>
      <span class="nav-label">Applications</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">📊</span>
      <span class="nav-label">Datasets</span>
    </a>
  </div>

  <!-- SECTION 2: Personal (all authenticated users) -->
  <div class="nav-section">
    <div class="nav-section-title">Personal</div>
    <a href="#" class="nav-item">
      <span class="nav-icon">📋</span>
      <span class="nav-label">My Sessions</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">⚙️</span>
      <span class="nav-label">Settings</span>
    </a>
  </div>

  <!-- SECTION 3: Organization (org_admin or global_admin) -->
  <div class="nav-section">
    <div class="nav-section-title">Organization</div>
    <a href="#" class="nav-item">
      <span class="nav-icon">🏢</span>
      <span class="nav-label">General</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">👥</span>
      <span class="nav-label">Members & Roles</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">🪙</span>
      <span class="nav-label">Platform Tokens</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">📝</span>
      <span class="nav-label">Transactions</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">🎁</span>
      <span class="nav-label">Gift Cards</span>
    </a>
  </div>

  <!-- SECTION 4: Admin (global_admin only) -->
  <div class="nav-section">
    <div class="nav-section-title">Admin</div>
    <a href="#" class="nav-item">
      <span class="nav-icon">💡</span>
      <span class="nav-label">Suggestions</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">🏛️</span>
      <span class="nav-label">Organizations</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">💰</span>
      <span class="nav-label">Payouts</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">📄</span>
      <span class="nav-label">Content</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">🚩</span>
      <span class="nav-label">Feature Flags</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">👤</span>
      <span class="nav-label">Consultants</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">📨</span>
      <span class="nav-label">RFIs</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">📋</span>
      <span class="nav-label">Invoice Requests</span>
      <span class="badge badge-count">3</span>
    </a>
  </div>

  <!-- SECTION 5: Developer (app_admin, org_admin, or dataset_admin) -->
  <div class="nav-section">
    <div class="nav-section-title">Developer</div>
    <a href="#" class="nav-item">
      <span class="nav-icon">📱</span>
      <span class="nav-label">Applications</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">📊</span>
      <span class="nav-label">Datasets</span>
    </a>
    <a href="#" class="nav-item">
      <span class="nav-icon">🔑</span>
      <span class="nav-label">JWT Testing</span>
    </a>
    <a href="#" class="nav-item external">
      <span class="nav-icon">💬</span>
      <span class="nav-label">Support Chat</span>
      <span class="external-icon">↗</span>
    </a>
  </div>

  <!-- SECTION 6: Support (all users) -->
  <div class="nav-section">
    <div class="nav-section-title">Support</div>
    <a href="#" class="nav-item external">
      <span class="nav-icon">❓</span>
      <span class="nav-label">Help</span>
      <span class="external-icon">↗</span>
    </a>
  </div>
</nav>
```

**Active State:** Add `.active` class to the current nav-item:
```html
<a href="#" class="nav-item active">
```

**Show Only Relevant Sections:** Based on the view's context, show only the navigation sections that user role would see. For marketplace views, show Marketplace + Personal. For admin views, show all sections.

### 3.3 MANDATORY: Page Content Structure

Every page follows this structure inside `<main class="page-content">`:

```html
<main class="page-content">
  <div class="page-container">
    <!-- 1. PAGE HEADER (always present) -->
    <div class="page-header">
      <div class="page-header-text">
        <h1 class="page-title">Page Title</h1>
        <p class="page-description">Optional description text</p>
      </div>
      <div class="page-header-actions">
        <button class="btn btn-outline">Secondary Action</button>
        <button class="btn btn-primary">Primary Action</button>
      </div>
    </div>

    <!-- 2. FILTERS/SEARCH (if applicable) -->
    <div class="page-filters">
      <input type="text" class="input search-input" placeholder="Search...">
      <select class="select filter-select">
        <option>All Categories</option>
      </select>
    </div>

    <!-- 3. CONTENT AREA -->
    <div class="page-body">
      <!-- Cards, tables, grids, etc. -->
    </div>
  </div>
</main>
```

### 3.4 Card Patterns

**Standard Card:**
```html
<div class="card">
  <div class="card-header">
    <h3 class="card-title">Card Title</h3>
    <p class="card-description">Description text</p>
  </div>
  <div class="card-content">
    <!-- Content -->
  </div>
  <div class="card-footer">
    <button class="btn btn-outline">Cancel</button>
    <button class="btn btn-primary">Save</button>
  </div>
</div>
```

**Card Hierarchy (Dark Mode):**
Use these classes for proper visual hierarchy in dark mode:
- `.card` or `.bg-card` - Default card background
- `.card-section` or `.bg-card-section` - Content sections (darker)
- `.card-metrics` or `.bg-card-metrics` - Metrics/stats (lighter)
- `.alert-info` or `.bg-alert-info` - Informational highlights (lightest)

**Two-Column Grid:**
```html
<div class="grid grid-cols-2 gap-4">
  <div class="card card-section">
    <!-- Left column content -->
  </div>
  <div class="card card-metrics">
    <!-- Right column content -->
  </div>
</div>
```

**Item Grid (Applications/Datasets):**
```html
<div class="grid grid-cols-4 gap-4">
  <div class="card item-card">
    <div class="item-image">
      <img src="placeholder.png" alt="Item">
    </div>
    <div class="item-content">
      <h4 class="item-title">Item Name</h4>
      <p class="item-description">Description</p>
    </div>
    <div class="item-footer">
      <span class="token-amount">50 SMART</span>
      <button class="btn btn-primary btn-sm">Launch</button>
    </div>
  </div>
</div>
```

### 3.5 Detail List Pattern

```html
<div class="card-content">
  <div class="detail-list">
    <div class="detail-item">
      <span class="detail-icon">📧</span>
      <span class="detail-label">Email:</span>
      <span class="detail-value">user@example.com</span>
    </div>
    <div class="detail-item">
      <span class="detail-icon">📅</span>
      <span class="detail-label">Created:</span>
      <span class="detail-value">Feb 10, 2026</span>
    </div>
  </div>
</div>
```

### 3.6 Loading & Empty States

**Loading Skeleton:**
```html
<div class="grid grid-cols-4 gap-4">
  <div class="skeleton-card">
    <div class="skeleton skeleton-image"></div>
    <div class="skeleton skeleton-title"></div>
    <div class="skeleton skeleton-text"></div>
  </div>
  <!-- Repeat 8 times -->
</div>
```

**Empty State:**
```html
<div class="empty-state">
  <div class="empty-icon">📭</div>
  <h3 class="empty-title">No items found</h3>
  <p class="empty-description">Description of why empty or how to add items</p>
  <button class="btn btn-primary">Add Item</button>
</div>
```

### 3.7 Modal Pattern (Use Sparingly!)

**IMPORTANT:** Per frontend-app guidelines, modals should ONLY be used for:
- Destructive actions (delete confirmations)
- Actions that cost money/tokens
- Critical warnings requiring acknowledgment

**DO NOT use modals for:** Primary workflows, navigation, viewing details.

```html
<div class="modal-overlay">
  <div class="modal">
    <div class="modal-header">
      <h3 class="modal-title">Confirm Delete</h3>
      <button class="modal-close">×</button>
    </div>
    <div class="modal-body">
      <p>Are you sure you want to delete this item? This action cannot be undone.</p>
    </div>
    <div class="modal-footer">
      <button class="btn btn-outline">Cancel</button>
      <button class="btn btn-destructive">Delete</button>
    </div>
  </div>
</div>
```

---

## Phase 4: Design System CSS Reference

### 4.1 CSS Variables (from frontend-app globals.css)

```css
:root {
  /* Brand Colors */
  --primary: 145 100% 49%;           /* #00FA64 - Green */
  --primary-foreground: 0 0% 7%;
  --secondary: 37 100% 50%;          /* #FF9B00 - Orange */
  --secondary-foreground: 0 0% 98%;

  /* Semantic Colors */
  --background: 0 0% 100%;           /* White */
  --foreground: 0 0% 7%;             /* Near black */
  --card: 0 0% 98%;                  /* Light gray */
  --card-foreground: 0 0% 7%;
  --muted: 0 0% 93%;                 /* Gray */
  --muted-foreground: 0 0% 47%;
  --accent: 0 0% 96%;
  --accent-foreground: 0 0% 7%;
  --destructive: 0 65% 59%;          /* Red */
  --destructive-foreground: 0 0% 98%;
  --border: 0 0% 90%;
  --input: 0 0% 90%;
  --ring: 145 100% 49%;

  /* Layout */
  --radius: 0rem;                    /* NO rounded corners */

  /* Typography */
  --font-family-body: 'Ubuntu', 'Helvetica Neue', sans-serif;
}

.dark {
  --background: 0 0% 13%;            /* Dark gray */
  --foreground: 0 0% 98%;            /* Near white */
  --card: 0 0% 10%;                  /* First level */
  --card-foreground: 0 0% 98%;
  --muted: 0 0% 15%;                 /* Second level */
  --muted-foreground: 0 0% 63%;
  --accent: 0 0% 20%;                /* Third level */
  --accent-foreground: 0 0% 98%;
  --border: 0 0% 18%;
  --input: 0 0% 18%;

  /* Card hierarchy for dark mode */
  --alert-info: 215 16% 47%;
  --card-metrics: 215 20% 21%;
  --card-section: 215 16% 12%;
}
```

### 4.2 Typography

| Element | Size | Weight | Class |
|---------|------|--------|-------|
| Page Title (h1) | 2.25rem (36px) | Bold | `.page-title`, `.text-3xl` |
| Section Title (h2) | 1.875rem (30px) | Semibold | `.text-2xl` |
| Card Title (h3) | 1.5rem (24px) | Semibold | `.card-title`, `.text-xl` |
| Subsection (h4) | 1.25rem (20px) | Medium | `.text-lg` |
| Body | 1rem (16px) | Regular | Default |
| Small | 0.875rem (14px) | Regular | `.text-sm` |
| Muted | - | - | `.text-muted-foreground` |

### 4.3 Button Variants

| Variant | Class | Usage |
|---------|-------|-------|
| Primary | `.btn-primary` | Main actions (green) |
| Secondary | `.btn-secondary` | Alternative actions (orange) |
| Outline | `.btn-outline` | Secondary actions |
| Ghost | `.btn-ghost` | Subtle actions |
| Destructive | `.btn-destructive` | Delete/danger actions (red) |
| Link | `.btn-link` | Text-style links |

### 4.4 Badge Variants

| Status | Class | Color |
|--------|-------|-------|
| Default | `.badge` | Primary (green) |
| Secondary | `.badge-secondary` | Orange |
| Outline | `.badge-outline` | Border only |
| Destructive | `.badge-destructive` | Red |
| Pending | `.badge-pending` | Yellow |
| Accepted | `.badge-accepted` | Green |
| Delivered | `.badge-delivered` | Blue |
| Completed | `.badge-completed` | Green |

### 4.5 Spacing

| Purpose | Classes |
|---------|---------|
| Page padding | `p-6` |
| Section gaps | `space-y-6`, `gap-6` |
| Card padding | `p-6` |
| Tight spacing | `space-y-2`, `gap-2` |
| Between items | `gap-4` |

---

## Phase 5: Capture Screenshots

### 5.1 Screenshot Each View

```typescript
for (const view of views) {
  // Light theme
  await mcp__chrome-devtools__navigate_page({
    type: "url",
    url: `file://${outputDir}/light/${view.filename}`
  });
  await mcp__chrome-devtools__take_screenshot({
    fullPage: true,
    filePath: `${outputDir}/screenshots/light-${view.name}.png`
  });

  // Dark theme
  await mcp__chrome-devtools__navigate_page({
    type: "url",
    url: `file://${outputDir}/dark/${view.filename}`
  });
  await mcp__chrome-devtools__take_screenshot({
    fullPage: true,
    filePath: `${outputDir}/screenshots/dark-${view.name}.png`
  });
}
```

---

## Phase 6: Generate Summary

```markdown
## Mockups Generated: [Feature Name]

**Source Plan:** [plan path]
**Output Directory:** project-docs/mockups/[feature]/

### Files Created

| Directory | Contents |
|-----------|----------|
| `design-system.css` | Standalone CSS with theme tokens |
| `light/` | [N] HTML files (light theme) |
| `dark/` | [N] HTML files (dark theme) |
| `screenshots/` | [2N] PNG screenshots |

### Views Created

| View | Nav Section | Description |
|------|-------------|-------------|
| view-name | Organization | Description |
```

---

## Anti-Patterns (AUTOMATIC FAILURE)

| Anti-Pattern | Correct Approach |
|--------------|------------------|
| Not using AppLayout structure | Every page MUST have sidebar + header + main |
| Wrong navigation section order | Follow exact frontend-app Sidebar.tsx order |
| Missing token meter in header | Header MUST show token balance |
| Using modals for primary navigation | Use dedicated pages with URLs |
| Rounded corners | Border radius MUST be 0 |
| Missing dark mode version | Create both light AND dark |
| Inventing navigation items | Only use items from frontend-app Sidebar.tsx |
| Skipping frontend-app reference check | MUST read actual source files first |
| Wrong card hierarchy in dark mode | Use card-section/card-metrics classes |

---

## Integration with Workflow Commands

This skill can be invoked:
- During `/plan` - Generate mockups for epic planning
- During `/groom` - Validate UI requirements have mockups
- Standalone - Generate mockups for any PRP document

**Invocation pattern:**
```markdown
## Phase N: Generate UI Mockups

> Skill reference: [mockups](.claude/skills/mockups.md)

Execute mockup generation for the PRP:
1. Read frontend-app layout components for current patterns
2. Parse UI sections from the plan
3. Generate HTML using exact AppLayout structure
4. Create light and dark theme versions
5. Capture screenshots for review

**Output:** Complete mockup set in project-docs/mockups/[feature]/
```

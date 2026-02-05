# iNTERCEPT UI Guide

This guide documents the UI design system, components, and patterns used in iNTERCEPT.

## Table of Contents

1. [Design Tokens](#design-tokens)
2. [Base Templates](#base-templates)
3. [Navigation](#navigation)
4. [Components](#components)
5. [Adding a New Module Page](#adding-a-new-module-page)
6. [Adding a New Dashboard](#adding-a-new-dashboard)

---

## Design Tokens

All design tokens are defined in `static/css/core/variables.css`. Import this file first in any stylesheet.

### Colors

```css
/* Backgrounds (layered depth) */
--bg-primary: #0a0c10;      /* Darkest - page background */
--bg-secondary: #0f1218;    /* Panels, sidebars */
--bg-tertiary: #151a23;     /* Cards, elevated elements */
--bg-card: #121620;         /* Card backgrounds */
--bg-elevated: #1a202c;     /* Hover states, modals */

/* Accent Colors */
--accent-cyan: #4a9eff;     /* Primary action color */
--accent-green: #22c55e;    /* Success, online status */
--accent-red: #ef4444;      /* Error, danger, stop */
--accent-orange: #f59e0b;   /* Warning */
--accent-amber: #d4a853;    /* Secondary highlight */

/* Text Hierarchy */
--text-primary: #e8eaed;    /* Main content */
--text-secondary: #9ca3af;  /* Secondary content */
--text-dim: #4b5563;        /* Disabled, placeholder */
--text-muted: #374151;      /* Barely visible */

/* Status Colors */
--status-online: #22c55e;
--status-warning: #f59e0b;
--status-error: #ef4444;
--status-offline: #6b7280;
```

### Spacing Scale

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--space-12: 48px;
--space-16: 64px;
```

### Typography

```css
/* Font Families */
--font-sans: 'Inter', -apple-system, sans-serif;
--font-mono: 'JetBrains Mono', monospace;

/* Font Sizes */
--text-xs: 10px;
--text-sm: 12px;
--text-base: 14px;
--text-lg: 16px;
--text-xl: 18px;
--text-2xl: 20px;
--text-3xl: 24px;
--text-4xl: 30px;
```

### Border Radius

```css
--radius-sm: 4px;
--radius-md: 6px;
--radius-lg: 8px;
--radius-xl: 12px;
--radius-full: 9999px;
```

### Light Theme

The design system supports light/dark themes via `data-theme` attribute:

```html
<html data-theme="dark">  <!-- or "light" -->
```

Toggle with JavaScript:
```javascript
document.documentElement.setAttribute('data-theme', 'light');
```

---

## Base Templates

### `templates/layout/base.html`

The main base template for standard pages. Use for pages with sidebar + content layout.

```html
{% extends 'layout/base.html' %}

{% block title %}My Page Title{% endblock %}

{% block styles %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/my-page.css') }}">
{% endblock %}

{% block navigation %}
{% set active_mode = 'mymode' %}
{% include 'partials/nav.html' %}
{% endblock %}

{% block sidebar %}
<div class="app-sidebar">
    <!-- Sidebar content -->
</div>
{% endblock %}

{% block content %}
<div class="page-container">
    <h1>Page Title</h1>
    <!-- Page content -->
</div>
{% endblock %}

{% block scripts %}
<script>
    // Page-specific JavaScript
</script>
{% endblock %}
```

### `templates/layout/base_dashboard.html`

Extended base for full-screen dashboards (maps, visualizations).

```html
{% extends 'layout/base_dashboard.html' %}

{% set active_mode = 'mydashboard' %}

{% block dashboard_title %}MY DASHBOARD{% endblock %}

{% block styles %}
{{ super() }}
<link rel="stylesheet" href="{{ url_for('static', filename='css/my_dashboard.css') }}">
{% endblock %}

{% block stats_strip %}
<div class="stats-strip">
    <!-- Stats bar content -->
</div>
{% endblock %}

{% block dashboard_content %}
<div class="dashboard-map-container">
    <!-- Main visualization -->
</div>
<div class="dashboard-sidebar">
    <!-- Sidebar panels -->
</div>
{% endblock %}
```

---

## Navigation

### Including Navigation

```html
{% set active_mode = 'pager' %}
{% include 'partials/nav.html' %}
```

### Valid `active_mode` Values

| Mode | Description |
|------|-------------|
| `pager` | Pager decoding |
| `sensor` | 433MHz sensors |
| `rtlamr` | Utility meters |
| `adsb` | Aircraft tracking |
| `ais` | Vessel tracking |
| `aprs` | Amateur radio |
| `wifi` | WiFi scanning |
| `bluetooth` | Bluetooth scanning |
| `tscm` | Counter-surveillance |
| `satellite` | Satellite tracking |
| `sstv` | ISS SSTV |
| `listening` | Listening post |
| `spystations` | Spy stations |
| `meshtastic` | Mesh networking |

### Navigation Groups

The navigation is organized into groups:
- **SDR / RF**: Pager, 433MHz, Meters, Aircraft, Vessels, APRS, Listening Post, Spy Stations, Meshtastic
- **Wireless**: WiFi, Bluetooth
- **Security**: TSCM
- **Space**: Satellite, ISS SSTV

---

## Components

### Card / Panel

```html
{% call card(title='PANEL TITLE', indicator=true, indicator_active=false) %}
<p>Panel content here</p>
{% endcall %}
```

Or manually:
```html
<div class="panel">
    <div class="panel-header">
        <span>PANEL TITLE</span>
        <div class="panel-indicator active"></div>
    </div>
    <div class="panel-content">
        <p>Content here</p>
    </div>
</div>
```

### Empty State

```html
{% include 'components/empty_state.html' with context %}
{# Or with variables: #}
{% with title='No data yet', description='Start scanning to see results', action_text='Start Scan', action_onclick='startScan()' %}
{% include 'components/empty_state.html' %}
{% endwith %}
```

### Loading State

```html
{# Inline spinner #}
{% include 'components/loading.html' %}

{# With text #}
{% with text='Loading data...', size='lg' %}
{% include 'components/loading.html' %}
{% endwith %}

{# Full overlay #}
{% with overlay=true, text='Please wait...' %}
{% include 'components/loading.html' %}
{% endwith %}
```

### Status Badge

```html
{% with status='online', text='Connected', id='connectionStatus' %}
{% include 'components/status_badge.html' %}
{% endwith %}
```

Status values: `online`, `offline`, `warning`, `error`, `inactive`

### Buttons

```html
<!-- Primary action -->
<button class="btn btn-primary">Start Tracking</button>

<!-- Secondary action -->
<button class="btn btn-secondary">Cancel</button>

<!-- Danger action -->
<button class="btn btn-danger">Stop</button>

<!-- Ghost/subtle -->
<button class="btn btn-ghost">Settings</button>

<!-- Sizes -->
<button class="btn btn-primary btn-sm">Small</button>
<button class="btn btn-primary btn-lg">Large</button>

<!-- Icon button -->
<button class="btn btn-icon btn-secondary">
    <span class="icon">...</span>
</button>
```

### Badges

```html
<span class="badge">Default</span>
<span class="badge badge-primary">Primary</span>
<span class="badge badge-success">Online</span>
<span class="badge badge-warning">Warning</span>
<span class="badge badge-danger">Error</span>
```

### Form Groups

```html
<div class="form-group">
    <label for="frequency">Frequency (MHz)</label>
    <input type="text" id="frequency" value="153.350">
    <span class="form-help">Enter frequency in MHz</span>
</div>

<div class="form-group">
    <label for="gain">Gain</label>
    <select id="gain">
        <option value="auto">Auto</option>
        <option value="30">30 dB</option>
    </select>
</div>

<label class="form-check">
    <input type="checkbox" id="alerts">
    <span>Enable alerts</span>
</label>
```

### Stats Strip

Used in dashboards for horizontal statistics display:

```html
<div class="stats-strip">
    <div class="stats-strip-inner">
        <div class="strip-stat">
            <span class="strip-value" id="count">0</span>
            <span class="strip-label">COUNT</span>
        </div>
        <div class="strip-divider"></div>
        <div class="strip-status">
            <div class="status-dot active" id="statusDot"></div>
            <span id="statusText">TRACKING</span>
        </div>
        <div class="strip-time" id="utcTime">--:--:-- UTC</div>
    </div>
</div>
```

---

## Adding a New Module Page

### 1. Create the Route

In `routes/mymodule.py`:

```python
from flask import Blueprint, render_template

mymodule_bp = Blueprint('mymodule', __name__, url_prefix='/mymodule')

@mymodule_bp.route('/dashboard')
def dashboard():
    return render_template('mymodule_dashboard.html',
                          offline_settings=get_offline_settings())
```

### 2. Register the Blueprint

In `routes/__init__.py`:

```python
from routes.mymodule import mymodule_bp
app.register_blueprint(mymodule_bp)
```

### 3. Create the Template

Option A: Simple page extending base.html
```html
{% extends 'layout/base.html' %}
{% set active_mode = 'mymodule' %}

{% block title %}My Module{% endblock %}

{% block navigation %}
{% include 'partials/nav.html' %}
{% endblock %}

{% block content %}
<!-- Your content -->
{% endblock %}
```

Option B: Full-screen dashboard
```html
{% extends 'layout/base_dashboard.html' %}
{% set active_mode = 'mymodule' %}

{% block dashboard_title %}MY MODULE{% endblock %}

{% block dashboard_content %}
<!-- Your dashboard content -->
{% endblock %}
```

### 4. Add to Navigation

In `templates/partials/nav.html`, add your module to the appropriate group:

```html
<button class="mode-nav-btn {% if active_mode == 'mymodule' %}active{% endif %}"
        onclick="switchMode('mymodule')">
    <span class="nav-icon icon"><!-- SVG icon --></span>
    <span class="nav-label">My Module</span>
</button>
```

Or if it's a dashboard link:
```html
<a href="/mymodule/dashboard"
   class="mode-nav-btn {% if active_mode == 'mymodule' %}active{% endif %}"
   style="text-decoration: none;">
    <span class="nav-icon icon"><!-- SVG icon --></span>
    <span class="nav-label">My Module</span>
</a>
```

### 5. Create Stylesheet

In `static/css/mymodule.css`:

```css
/**
 * My Module Styles
 */
@import url('./core/variables.css');

/* Your styles using design tokens */
.mymodule-container {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: var(--space-4);
}
```

---

## Adding a New Dashboard

For full-screen dashboards like ADSB, AIS, or Satellite:

### 1. Create the Template

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MY DASHBOARD // iNTERCEPT</title>
    <link rel="icon" type="image/svg+xml" href="{{ url_for('static', filename='favicon.svg') }}">

    <!-- Design tokens (required) -->
    <link rel="stylesheet" href="{{ url_for('static', filename='css/core/variables.css') }}">

    <!-- Fonts -->
    {% if offline_settings.fonts_source == 'local' %}
    <link rel="stylesheet" href="{{ url_for('static', filename='css/fonts-local.css') }}">
    {% else %}
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    {% endif %}

    <!-- External libraries if needed -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <!-- Dashboard styles -->
    <link rel="stylesheet" href="{{ url_for('static', filename='css/responsive.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/mydashboard.css') }}">
</head>
<body>
    <!-- Background effects -->
    <div class="radar-bg"></div>
    <div class="scanline"></div>

    <!-- Header -->
    <header class="header">
        <div class="logo">
            <a href="/" style="color: inherit; text-decoration: none;">
                MY DASHBOARD
                <span>// iNTERCEPT</span>
            </a>
        </div>
        <div class="status-bar">
            <a href="#" onclick="history.back(); return false;" class="back-link">Back</a>
            <a href="/" class="back-link">Main Dashboard</a>
        </div>
    </header>

    <!-- Unified Navigation -->
    {% set active_mode = 'mydashboard' %}
    {% include 'partials/nav.html' %}

    <!-- Stats Strip -->
    <div class="stats-strip">
        <!-- Stats content -->
    </div>

    <!-- Main Dashboard Content -->
    <main class="dashboard">
        <!-- Your dashboard layout -->
    </main>

    <script>
        // Dashboard JavaScript
    </script>
</body>
</html>
```

### 2. Create the Stylesheet

```css
/**
 * My Dashboard Styles
 */
@import url('./core/variables.css');

:root {
    /* Dashboard-specific aliases */
    --bg-dark: var(--bg-primary);
    --bg-panel: var(--bg-secondary);
    --bg-card: var(--bg-tertiary);
    --grid-line: rgba(74, 158, 255, 0.08);
}

/* Your dashboard styles */
```

---

## Best Practices

### DO

- Use design tokens for all colors, spacing, and typography
- Include the nav partial on all pages for consistent navigation
- Set `active_mode` before including the nav partial
- Use semantic component classes (`btn`, `panel`, `badge`, etc.)
- Support both light and dark themes
- Test on mobile viewports

### DON'T

- Hardcode color values - use CSS variables
- Create new color variations without adding to tokens
- Duplicate navigation markup - use the partial
- Skip the favicon and design tokens imports
- Use inline styles for layout (use utility classes)

---

## File Structure

```
templates/
├── layout/
│   ├── base.html              # Standard page base
│   └── base_dashboard.html    # Dashboard page base
├── partials/
│   ├── nav.html               # Unified navigation
│   ├── page_header.html       # Page title component
│   └── settings-modal.html    # Settings modal
├── components/
│   ├── card.html              # Panel/card component
│   ├── empty_state.html       # Empty state placeholder
│   ├── loading.html           # Loading spinner
│   ├── stats_strip.html       # Stats bar component
│   └── status_badge.html      # Status indicator
├── index.html                 # Main dashboard
├── adsb_dashboard.html        # Aircraft tracking
├── ais_dashboard.html         # Vessel tracking
└── satellite_dashboard.html   # Satellite tracking

static/css/
├── core/
│   ├── variables.css          # Design tokens
│   ├── base.css               # Reset & typography
│   ├── components.css         # Component styles
│   └── layout.css             # Layout styles
├── index.css                  # Main dashboard styles
├── adsb_dashboard.css         # Aircraft dashboard
├── ais_dashboard.css          # Vessel dashboard
├── satellite_dashboard.css    # Satellite dashboard
└── responsive.css             # Responsive breakpoints
```

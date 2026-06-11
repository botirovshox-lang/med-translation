# Design Brief for Claude Design - Medical CAT Translator v5.5
## ADHD-Friendly UI/UX with Minimalist Professional Design

**Project:** Medical CAT Translator v5.5 - Advanced Medical Document Translation System  
**Target Users:** Medical translators (some with ADHD)  
**Design Approach:** Minimalist, spacious, high-contrast, intuitive, professional  
**Status:** Production-ready application needing UI/UX redesign  
**Output:** Complete design system with light/dark themes

---

## 🎯 DESIGN PRINCIPLES FOR ADHD USERS

### Visual Hierarchy & Cognitive Load
- ✅ **Minimize visual clutter** - Use white/negative space generously
- ✅ **Clear visual hierarchy** - Large typography gaps between sections (h1: 32px, h2: 24px, h3: 18px)
- ✅ **One primary action per section** - Secondary actions in dropdowns/expanders
- ✅ **High contrast** - WCAG AAA compliance (contrast ratio ≥ 7:1 for text)
- ✅ **Consistent spacing** - 8px/16px/24px/32px grid throughout
- ✅ **Color coding** - Status indicated by color + icon + text (not color alone)

### Reduce Decision Fatigue
- ✅ **Sensible defaults** - Pre-filled values, smart suggestions
- ✅ **Progressive disclosure** - Advanced options in expandable sections
- ✅ **Clear call-to-action buttons** - Primary actions prominent, secondary muted
- ✅ **Confirmation dialogs** - For destructive actions (delete, reset)
- ✅ **State indicators** - Always show current status visually

### Attention & Focus
- ✅ **Focus states** - Clear keyboard navigation (outline: 2px, color varies by theme)
- ✅ **No auto-play animations** - Static by default, user-triggered if needed
- ✅ **Loading states** - Spinner + progress text (e.g., "Translating... 45/120 segments")
- ✅ **Success/error feedback** - Toast notifications (auto-dismiss after 5s)
- ✅ **Breakout indicators** - Visual cues for important/urgent items (warning colors, badges)

### Readability
- ✅ **Font:** Inter or -apple-system, sans-serif (open dyslexia NOT needed, high contrast enough)
- ✅ **Line height:** 1.6 for body text, 1.4 for UI labels
- ✅ **Max width:** 80-100 characters per line in text blocks
- ✅ **Letter spacing:** +0.3px for improved readability
- ✅ **Avoid:** Justified text, all-caps for long text, blinking/flashing

---

## 📱 LAYOUT STRUCTURE

### 1️⃣ Authentication Screen
**Path:** Initial load (before app)

**Components:**
- Center-aligned card (max-width: 400px)
- Logo/Title: "🔐 Medical CAT Translator v5.5"
- Subtitle: "Advanced Medical Document Translation"
- Password input field (masked)
- Two buttons: "🔓 Login" (primary, blue), "ℹ️ Help" (secondary, outline)
- Footer: Small gray text with copyright

**Spacing:**
- Top margin: 60px (center vertically on screen)
- Padding inside card: 32px
- Gap between elements: 16px

**Dark theme variant:**
- Card bg: #1e1e1e (very dark gray)
- Text: #e0e0e0 (light gray)
- Input bg: #2a2a2a
- Button primary: #3b82f6 (bright blue)

**Light theme variant:**
- Card bg: #ffffff (white)
- Text: #1a1a1a (dark gray)
- Input bg: #f5f5f5 (light gray)
- Button primary: #0066cc (darker blue)

---

### 2️⃣ Main App Layout
**After authentication**

**Structure:**
```
┌─────────────────────────────────────────┐
│ Header: Title + Breadcrumb + User Menu  │ (h: 56px)
├─────────────────────────────────────────┤
│ Tabs (horizontal scroll if needed)      │ (h: 48px)
├─────────────────────────────────────────┤
│                                         │
│  Main Content Area (Tab Content)        │ (flex: 1)
│                                         │
│  + Right Sidebar (optional, collapsible)│ (w: 320px)
│                                         │
└─────────────────────────────────────────┘
```

**Header:**
- Logo/Title left: "🏥 Medical CAT Translator v5.5"
- Right: [🔍 Search] [⚙️ Settings] [👤 User] [🔐 Logout]
- Background: Slightly different from main (subtle contrast)
- Sticky: Yes, follows scroll

**Tabs (9 total):**
- 📥 Import DOCX
- ✏️ Segment Editor
- 📚 Glossary
- 🔁 TM
- 📤 Export
- 🔍 Preflight
- ✔️ QA Dashboard
- 📋 Backlog
- 📊 Stats

**Tab styling:**
- Inactive: Gray text, white/transparent bg
- Active: Blue text (or theme color), white bg with bottom border (2px blue)
- Hover: Light gray bg
- Icon + Text in all tabs
- Responsive: On mobile, scrollable horizontal

---

## 🔍 TAB DETAILS

### TAB 0: Import DOCX
**Purpose:** Create new translation projects from Word documents

**Content Layout:**
```
Section 1: File Upload
├─ Upload Area (drag-drop or click)
│  └─ Large icon + "Drop DOCX here or click to upload"
├─ Project Title input (with placeholder "e.g., Medical Paper 2026")
├─ Source Language (default: Russian)
├─ Target Language (default: English)
└─ Button: "▶️ Create Project" (primary, disabled until file uploaded)

Section 2: Existing Projects (if any)
├─ Heading: "Your Projects"
├─ Card layout (NOT table - cards for ADHD-friendly browsing)
│  └─ Each project card:
│     ├─ Title (bold)
│     ├─ Info row: "📊 145 segments | 🌍 RU→EN"
│     ├─ Status badge: "In Progress" (yellow)
│     └─ Quick actions: [📝 Edit] [📤 Export]
```

**Colors:**
- Upload area: Light dashed border (2px, gray)
- Hover: Blue dashed border
- Card bg: White (light) / #2a2a2a (dark)
- Buttons: Blue for primary, outlined for secondary

---

### TAB 1: Segment Editor (MOST IMPORTANT)
**Purpose:** Translate, review, and approve individual text segments

**Main Content:**
```
Section A: Project & Filter Controls (Sticky, h: 140px)
├─ Row 1:
│  ├─ Project selector: Dropdown "📁 Project #7 — Medical Paper 2026"
│  └─ [Spacing]
├─ Row 2:
│  ├─ Status filter: "⏹ All | 📝 New | ✅ Translated | ✔️ QA Done | ✓ Confirmed"
│  ├─ Table height slider: "Table Height: ▬▬▬▬▬ 400px"
│  └─ Advanced filters: [⚙️ More filters] (expandable)
└─ Row 3: Delete warning (if project empty)

Section B: Batch Actions (Two subsections, collapsible)
├─ Google Batch
│  ├─ Heading: "🌐 Google Batch (Low-risk segments)"
│  ├─ Button row: [📊 Preview] [▶️ Run] [📏 Size: 50] [⚙️ Settings]
│  └─ Info: "Use for simple, low-risk translations"
└─ GPT Batch
   ├─ Heading: "🤖 GPT Batch (Complex content)"
   ├─ Button row: [📊 Preview] [▶️ Run] [⚙️ Model: GPT-4o-mini]
   └─ Info: "Use for complex medical content"

Section C: Main Table (Scrollable, virtualized for 1000+ rows)
├─ Columns (resizable):
│  ├─ # (segment ID)
│  ├─ 🇷🇺 Source Text (60% width)
│  ├─ 🇬🇧 Translation (60% width, editable)
│  ├─ Status (badge)
│  ├─ Actions (buttons: Translate, QA, Confirm)
│  └─ Menu (⋮)
└─ Row colors:
   ├─ New: Light gray bg
   ├─ Translated: Light blue bg
   ├─ Confirmed: Light green bg
   └─ Failed: Light red bg

Section D: Selected Segment Details (Right sidebar, 320px)
├─ When segment selected:
│  ├─ Header: "Segment #47 of 145"
│  ├─ Source text (read-only, copyable)
│  ├─ [🔄 Quick Copy] button
│  ├─ Translation input (editable)
│  ├─ Word count: "45 words | 250 chars"
│  ├─ Tabs below:
│  │  ├─ 💡 Context (source + glossary terms)
│  │  ├─ 📝 TM Suggestions (if any 100% matches)
│  │  ├─ ⚠️ QA Results (if QA ran)
│  │  └─ 💬 Comments
│  └─ Action buttons:
│     ├─ [🌐 Translate (Google)]
│     ├─ [🤖 Translate (GPT)]
│     ├─ [✅ QA Check]
│     └─ [✓ Confirm]

Section E: Correction & Comments Block (Below translation)
├─ Collapsible expander: "💬 Comments & Corrections"
├─ Comment history (scrollable, max 300px):
│  └─ Each comment:
│     ├─ User avatar + name
│     ├─ Timestamp (relative: "2 hours ago")
│     └─ Comment text
└─ New comment input:
   ├─ Text area (auto-expand on focus)
   └─ Button: [💬 Add Comment] (secondary)
```

**Color Coding (Status):**
- New/Untranslated: Gray badge "📝 New"
- Translated (not QA'd): Blue badge "🌐 Translated"
- QA Complete: Orange badge "✔️ QA Done"
- Confirmed: Green badge "✓ Confirmed"
- Failed: Red badge "❌ Failed"
- Needs Review: Yellow badge "⚠️ Review"

**Buttons (All segments have same layout):**
- Primary: "🌐 Translate" (blue, full width in details panel)
- Secondary: "✅ QA" (outlined, secondary color)
- Tertiary: "✓ Confirm" (ghost, green on success)

---

### TAB 2: Glossary
**Purpose:** Manage medical terminology and approved terms

**Content:**
```
Section A: Controls (Sticky)
├─ Search box: "🔍 Search glossary..." (full width)
└─ Buttons: [➕ Add Term] [📥 Import TSV] [📤 Export TSV]

Section B: Glossary Table
├─ Columns:
│  ├─ Source term (medical Russian)
│  ├─ Target term (English equivalent)
│  ├─ Category (Anatomy, Dosage, Disease, etc.)
│  ├─ Frequency (used X times)
│  └─ Actions: [✏️ Edit] [🗑️ Delete]
├─ Filter: [Category dropdown] [Sort by frequency]
└─ Count: "Showing 487 terms"

Section C: Add/Edit Term Modal (Popup)
├─ Field: Source term (Russian) - text input
├─ Field: Target term (English) - text input
├─ Field: Category - dropdown (Anatomy, Dosage, Device, Disease, etc.)
├─ Field: Notes (optional) - text area
├─ Field: Confidence - radio (High, Medium, Low)
└─ Buttons: [Save] [Cancel]
```

---

### TAB 3: TM (Translation Memory)
**Purpose:** View and manage exact matches from previous translations

**Content:**
```
Section A: Controls
├─ Search: "🔍 Search TM..." 
├─ Filter: [Source language] [Target language]
└─ Buttons: [📥 Import TMX] [📤 Export TMX]

Section B: TM Entries (Card layout)
├─ Each card:
│  ├─ Source text (Russian, 2 lines max with ellipsis)
│  ├─ Translation (English, 2 lines max with ellipsis)
│  ├─ Metadata: "Created 3 months ago | Used 12 times"
│  ├─ Quality badge: "✅ Verified" or "⚠️ Draft"
│  └─ Actions: [📋 Copy] [✏️ Edit] [🗑️ Delete]
```

---

### TAB 4: Export
**Purpose:** Download translated document

**Content:**
```
Section A: Export Format Selection
├─ Radio buttons:
│  ├─ ☑️ DOCX (Microsoft Word - preserves formatting)
│  ├─ ☐ PDF (Read-only - good for review)
│  └─ ☐ Excel (Spreadsheet format)
└─ Help text: "DOCX recommended for most cases"

Section B: Content Options
├─ ☑️ Include source text in comments
├─ ☑️ Include translator notes
├─ ☑️ Include QA results
└─ ☑️ Include glossary references

Section C: Export Button
└─ Large primary button: [📤 Download File]

Section D: Export History
├─ Heading: "Recent Exports"
├─ List:
│  └─ Each item: "medical_paper_v3.docx" + "Downloaded 2 hours ago" + [🔄 Re-export]
```

---

### TAB 5: Preflight
**Purpose:** Analyze project before translation (routing, costs, risks)

**Content:**
```
Section A: Analysis Controls
├─ Status: "Last analyzed: 2 hours ago"
├─ Info: "Analyzed 145 segments"
└─ Button: [🔍 Analyze Now] (primary, if outdated)

Section B: Key Metrics (4 cards in 2x2 grid)
├─ Card 1: "Total Segments: 145"
├─ Card 2: "Exact TM Matches: 23 (16%)"
├─ Card 3: "Estimated Cost: $12.50"
└─ Card 4: "Avg Complexity: Medium"

Section C: Routing Breakdown (Horizontal bar chart)
├─ EXACT_TM: 23 segments (blue) — $0
├─ DUPLICATE: 15 segments (green) — $0
├─ GOOGLE_SAFE: 42 segments (yellow) — $0
├─ GPT_REQUIRED: 65 segments (purple) — $12.50
└─ HUMAN_REVIEW: 0 segments (red) — $0

Section D: Risk Summary (Expandable)
├─ Low risk: 80 segments
├─ Medium risk: 55 segments
├─ High risk: 10 segments
└─ Critical: 0 segments

Section E: Glossary Coverage
├─ Coverage: 68% (info: "How many segments have glossary matches?")
├─ Missing terms: 15 (info: "Terms mentioned but not in glossary")
└─ Recommended: "Add 5 critical medical terms to glossary"
```

---

### TAB 6: QA Dashboard
**Purpose:** Quality assurance results and corrections

**Content:**
```
Section A: QA Status Summary (3 columns)
├─ Column 1: "✅ Passed QA: 45 segments"
├─ Column 2: "⚠️ Warnings: 12 segments"
└─ Column 3: "❌ Failed: 3 segments"

Section B: Issue Breakdown (Expandable cards)
├─ Card: "🔤 Formatting Issues (5)"
│  └─ "Inconsistent capitalization in 5 segments"
├─ Card: "🔢 Numerical Errors (3)"
│  └─ "Mismatch in numbers/units in 3 segments"
├─ Card: "⚠️ Terminology Warnings (12)"
│  └─ "Forbidden or unusual terms detected"
└─ Card: "📏 Length Issues (2)"
   └─ "Translation significantly longer/shorter"

Section C: Detailed Issues List
├─ Each issue row:
│  ├─ Severity badge (🔴 Critical, 🟠 High, 🟡 Medium)
│  ├─ Segment #47
│  ├─ Issue type: "Terminology warning"
│  ├─ Details: "Term 'ПКБ' not in approved glossary"
│  └─ Action button: [🔧 Fix]
```

---

### TAB 7: Backlog
**Purpose:** Task management and translation priorities

**Content:**
```
Section A: Priority Filters
├─ Buttons: [🔴 Urgent] [🟠 High] [🟡 Medium] [🟢 Low]
└─ View: [📝 List] [📊 Board] [📅 Timeline]

Section B: Task Cards (Kanban-style columns)
├─ Column 1: "📝 New (23)"
├─ Column 2: "🔄 In Progress (8)"
├─ Column 3: "✅ Translated (45)"
└─ Column 4: "✓ Confirmed (69)"

Section C: Individual Task Card
├─ Segment #47
├─ Title: "Medical document excerpt 2.1"
├─ Status: "In Progress" (blue label)
├─ Priority: "🟠 High"
├─ Assigned to: "Dr. Smith"
├─ Due: "Tomorrow at 5 PM"
├─ Comments: "2 new comments"
└─ Actions: [➡️ Move] [👤 Assign] [⏰ Reschedule]
```

---

### TAB 8: Statistics
**Purpose:** Project overview and metrics

**Content:**
```
Section A: Progress Overview
├─ Large progress ring (circular): "65% Complete"
├─ Breakdown below ring:
│  ├─ Translated: 94 segments (65%)
│  ├─ QA Done: 89 segments (61%)
│  └─ Confirmed: 82 segments (57%)

Section B: Timeline (Horizontal bar)
├─ "Project timeline: 2 weeks elapsed / 4 weeks total (50%)"
├─ Visual: Progress bar with today marker

Section C: Team Activity (Facepile + stats)
├─ Avatars: (👤1, 👤2, 👤3, +2 more)
├─ Total contributors: 5
├─ Most active: "Dr. Smith (67 edits)"
└─ Activity chart: Line graph (segments translated per day)

Section D: Effort Metrics
├─ Avg time per segment: 4 min 23 sec
├─ Total hours invested: 12.5 hours
├─ Projected completion: "Tomorrow at 3 PM"
└─ Velocity: "23 segments/hour"

Section E: Cost Breakdown (Pie chart)
├─ TM Matches: $0
├─ Google Translate: $3.20
├─ GPT-4: $8.75
├─ Total Cost: $11.95
└─ Budget remaining: $38.05 / $50.00 budget
```

---

## 🎨 COLOR SYSTEM

### Light Theme
```
Primary Colors:
├─ Brand Blue: #0066cc (buttons, links, active tabs)
├─ Success Green: #22c55e (confirmed, passed QA)
├─ Warning Yellow: #f59e0b (caution, review needed)
├─ Error Red: #ef4444 (failed, errors)
└─ Info Cyan: #06b6d4 (information, hints)

Neutrals:
├─ Black: #1a1a1a (text, dark elements)
├─ Dark Gray: #4b5563 (secondary text)
├─ Medium Gray: #9ca3af (borders, disabled)
├─ Light Gray: #f3f4f6 (backgrounds, sections)
└─ White: #ffffff (primary background)

Status Backgrounds:
├─ New: #f0f9ff (very light blue)
├─ Translated: #dbeafe (light blue)
├─ Confirmed: #dcfce7 (light green)
├─ Failed: #fee2e2 (light red)
└─ Pending: #fef3c7 (light yellow)
```

### Dark Theme
```
Primary Colors:
├─ Brand Blue: #3b82f6 (buttons, links, active tabs) — BRIGHTER than light
├─ Success Green: #10b981 (confirmed, passed QA)
├─ Warning Yellow: #f59e0b (caution, review needed)
├─ Error Red: #f87171 (failed, errors)
└─ Info Cyan: #06b6d4 (information, hints)

Neutrals:
├─ White: #e0e0e0 (text, light elements)
├─ Light Gray: #9ca3af (secondary text)
├─ Medium Gray: #6b7280 (borders, disabled)
├─ Dark Gray: #2a2a2a (section backgrounds)
└─ Black: #1e1e1e (primary background)

Status Backgrounds:
├─ New: #1e3a8a (very dark blue)
├─ Translated: #1e40af (dark blue)
├─ Confirmed: #065f46 (dark green)
├─ Failed: #7f1d1d (dark red)
└─ Pending: #78350f (dark yellow)

Special:
├─ Card bg: #2a2a2a
├─ Input bg: #3a3a3a
├─ Hover bg: #383838
└─ Border: #4a4a4a (rgba(255,255,255,0.1) alternative)
```

---

## 🔘 BUTTON STYLES

### Primary Buttons (Call-to-Action)
```
Light Theme:
├─ Background: #0066cc
├─ Text: #ffffff
├─ Hover: #0052a3 (darker)
├─ Pressed: #004080 (even darker)
└─ Disabled: #cccccc (gray)

Dark Theme:
├─ Background: #3b82f6 (brighter blue for contrast)
├─ Text: #ffffff
├─ Hover: #2563eb
├─ Pressed: #1d4ed8
└─ Disabled: #6b7280 (gray)

Styling:
├─ Padding: 12px 24px (medium buttons)
├─ Border radius: 6px
├─ Font weight: 600
├─ Min width: 100px
└─ Transition: 150ms ease
```

### Secondary Buttons (Alternative actions)
```
Light Theme:
├─ Background: transparent
├─ Border: 2px #0066cc
├─ Text: #0066cc
├─ Hover: #f0f9ff (light blue bg)

Dark Theme:
├─ Background: transparent
├─ Border: 2px #3b82f6
├─ Text: #3b82f6
├─ Hover: #1e3a8a (dark blue bg)

Styling:
├─ Padding: 10px 22px (account for border)
├─ Border radius: 6px
└─ Transition: 150ms ease
```

### Tertiary/Ghost Buttons (Less important)
```
Light Theme:
├─ Background: transparent
├─ Text: #4b5563 (gray)
├─ Hover: #e5e7eb (light gray bg)

Dark Theme:
├─ Background: transparent
├─ Text: #9ca3af (light gray)
├─ Hover: #4a4a4a (dark gray bg)

Styling:
├─ Padding: 8px 16px
├─ No border
└─ Transition: 150ms ease
```

### Icon Buttons (Small, 32x32px)
```
Light & Dark:
├─ Size: 32x32px or 40x40px
├─ Hover: 10% darker (light) / 10% lighter (dark)
└─ Icon size: 16px or 20px
```

---

## 📝 FORM ELEMENTS

### Text Inputs
```
Light Theme:
├─ Background: #f5f5f5 (light gray)
├─ Border: 1px #d1d5db (gray)
├─ Border-radius: 6px
├─ Padding: 10px 12px
├─ Focus: Border 2px #0066cc (blue), shadow: 0 0 0 3px rgba(0,102,204,0.1)

Dark Theme:
├─ Background: #3a3a3a
├─ Border: 1px #4a4a4a
├─ Border-radius: 6px
├─ Padding: 10px 12px
├─ Focus: Border 2px #3b82f6 (blue), shadow: 0 0 0 3px rgba(59,130,246,0.2)

Placeholder text (both):
└─ Color: Medium gray (50% opacity)
```

### Dropdowns/Selects
```
Same styling as text inputs
├─ Indicate dropdown with ▼ icon right-aligned (12px from edge)
├─ On open: dropdown panel appears below (8px gap)
├─ Focus on option: Light blue bg (#e0f2fe light, #1e3a8a dark)
```

### Checkboxes
```
Light Theme:
├─ Unchecked: 18x18px white box, 2px border #d1d5db
├─ Checked: 18x18px blue box #0066cc, white ✓ checkmark
├─ Focus: 2px blue outline, 4px offset

Dark Theme:
├─ Unchecked: 18x18px transparent, 2px border #6b7280
├─ Checked: 18x18px blue #3b82f6, white ✓ checkmark
├─ Focus: 2px blue outline, 4px offset
```

### Radio Buttons
```
Light Theme:
├─ Unchecked: 18x18px white circle, 2px border #d1d5db
├─ Checked: 18x18px white circle, 2px border #0066cc, 8px blue center dot
├─ Focus: 2px blue outline, 4px offset

Dark Theme:
├─ Unchecked: 18x18px transparent, 2px border #6b7280
├─ Checked: 18x18px transparent, 2px border #3b82f6, 8px blue center dot
├─ Focus: 2px blue outline, 4px offset
```

### Text Areas
```
Same as text inputs but multi-line
├─ Min height: 100px (or match content)
├─ Resize: Vertical only (or none for auto-expand)
└─ Scroll: Smooth
```

---

## 📊 COMPONENTS

### Card Components
```
Structure:
├─ Background: White (light) / #2a2a2a (dark)
├─ Border: 1px #e5e7eb (light) / #4a4a4a (dark)
├─ Border-radius: 8px
├─ Padding: 16px-24px
├─ Box-shadow: 0 1px 3px rgba(0,0,0,0.1) (light) / 0 1px 3px rgba(0,0,0,0.3) (dark)
├─ Hover: Shadow increases slightly, no bg change
└─ Transition: 150ms ease

Usage:
├─ Project cards
├─ Task cards
├─ Status cards
└─ Info cards
```

### Badge Components
```
Statuses (all variants):
├─ Background: Colored (status-specific)
├─ Text: White or black (high contrast)
├─ Border-radius: 12px (pill shape)
├─ Padding: 4px 8px (compact)
├─ Font size: 12px
├─ Font weight: 600
└─ Display: Inline-block

Examples:
├─ "✅ Confirmed" (green)
├─ "⚠️ Review" (yellow)
├─ "❌ Failed" (red)
└─ "📝 In Progress" (blue)
```

### Alert/Toast Notifications
```
Structure:
├─ Position: Bottom-right (desktop) / Top-center (mobile)
├─ Width: 360px (desktop) / 100% - 16px (mobile)
├─ Min height: 64px
├─ Padding: 16px
├─ Border-radius: 8px
├─ Box-shadow: 0 10px 25px rgba(0,0,0,0.15)
├─ Auto-dismiss: 5000ms (5 seconds)
└─ Animation: Slide up + fade in (200ms), fade out (200ms)

Types:
├─ Success: Green bg #22c55e, white text
├─ Error: Red bg #ef4444, white text
├─ Warning: Yellow bg #f59e0b, dark text
└─ Info: Blue bg #0066cc, white text

Structure inside:
├─ Icon (left, 20x20px)
├─ Title (bold, flex: 1)
├─ Message (optional, secondary text)
└─ Close button (×, right)
```

### Expandable Sections
```
Structure:
├─ Header: Clickable, padding 16px
├─ Icon: ▶ (collapsed) / ▼ (expanded), left-aligned
├─ Title: Bold, flex: 1
├─ Right info (optional): "5 items" or count
├─ Body: Padding 16px, border-top (if expanded)
└─ Transition: Max-height 200ms ease

Styling:
├─ Header hover: Slight background change
├─ Body bg: Slightly different (gray section)
└─ Border: 1px #e5e7eb (light) / 1px #4a4a4a (dark)
```

### Modal Dialogs
```
Overlay:
├─ Background: rgba(0,0,0,0.5) (both themes)
├─ Transition: Fade 200ms

Modal box:
├─ Max width: 600px
├─ Border-radius: 12px
├─ Padding: 24px
├─ Box-shadow: 0 20px 50px rgba(0,0,0,0.2)
├─ Header: Title + close button (×)
├─ Body: Content (scrollable if > 60vh)
├─ Footer: Buttons (Cancel, Save/Confirm)
└─ Animation: Scale up + fade in (200ms)

Colors:
├─ Light: White bg #ffffff
└─ Dark: Dark gray bg #2a2a2a
```

### Progress Indicators
```
Progress Bar (Linear):
├─ Height: 4px
├─ Background: Light gray
├─ Fill: Blue #0066cc (light) / #3b82f6 (dark)
├─ Border-radius: 2px
└─ Animation: Smooth transition

Progress Ring (Circular):
├─ Size: 120px diameter (or variable)
├─ Stroke width: 8px
├─ Background: Light gray circle
├─ Fill: Blue circle from top, clockwise
├─ Center text: "65%" (bold, 24px)
└─ Animation: Smooth stroke animation

Spinner (for loading):
├─ Size: 24px or 40px
├─ Style: Rotating circle, blue #0066cc / #3b82f6
├─ Speed: 1s per rotation
└─ Ease: Linear
```

---

## ⌨️ KEYBOARD & ACCESSIBILITY

### Focus States
```
All interactive elements must have focus indicator:
├─ Desktop: 2px outline (blue #0066cc light, #3b82f6 dark)
├─ Offset: 4px from element
├─ Never remove focus outline (accessibility crucial)
├─ Tab order: Logical (top to bottom, left to right)
└─ Skip links: Jump to main content (hidden, revealed on focus)

Focus visible color contrast:
├─ Light theme: 2px #0066cc outline on white = Good
├─ Dark theme: 2px #3b82f6 outline on dark = Good
└─ WCAG AAA compliant
```

### Touch/Mobile
```
Target size: Minimum 44x44px (iOS standard)
├─ Buttons: 48x48px minimum
├─ Touch states: Larger hover area (50px)
└─ Spacing between clickables: 8px minimum
```

---

## 📐 SPACING & GRID

### Spacing Scale (8px base)
```
xs:  4px
sm:  8px
md: 16px
lg: 24px
xl: 32px
2xl: 48px
3xl: 64px
```

### Grid System
```
Desktop: 12-column grid
├─ Column width: Variable based on viewport
├─ Gutter: 16px (8px each side)
└─ Max content width: 1200px

Tablets: 6-column grid
└─ Gutter: 12px

Mobile: 4-column grid
└─ Gutter: 8px

Margins/Padding: Multiples of 8px
└─ Use: 8, 16, 24, 32, 48px (avoid 7px, 13px, etc.)
```

---

## 🎬 ANIMATIONS & TRANSITIONS

### All transitions: 150-200ms ease-in-out (except loaders)

**Entrance animations:**
├─ Fade in: Opacity 0 → 1 (200ms)
├─ Slide up: Transform translateY(10px) → 0 (200ms)
├─ Scale: Transform scale(0.95) → 1 (150ms)

**Hover states:**
├─ Button: Darker/lighter + shadow (150ms)
├─ Card: Shadow increase (150ms)
├─ Link: Color change (150ms)

**Loading indicators:**
├─ Spinner: Continuous rotation (1s, linear)
├─ Skeleton: Pulse effect (2s, infinite)

**Avoid:**
├─ Flashing/blinking (accessibility issue)
├─ Auto-play animations (ADHD-friendly)
├─ Transitions > 300ms (feels sluggish)
└─ Too many concurrent animations
```

---

## 📱 RESPONSIVE BREAKPOINTS

```
Mobile (default): 0px - 640px
├─ Single column layout
├─ Full-width buttons
├─ Sidebar → Bottom nav
└─ Table → Card view

Tablet: 641px - 1024px
├─ 2 columns where applicable
├─ Sidebar visible (narrow)
└─ Medium buttons

Desktop: 1025px+
├─ Full layout with sidebar
├─ All features visible
└─ Multi-column layouts
```

---

## 🌙 DARK MODE IMPLEMENTATION

**User preference:**
├─ System preference (prefers-color-scheme: dark)
├─ Manual toggle in settings
├─ Remember user choice (localStorage)
└─ Default to system preference

**CSS variables for theming:**
```css
:root {
  --color-primary: #0066cc;
  --color-success: #22c55e;
  /* etc. */
}

@media (prefers-color-scheme: dark) {
  :root {
    --color-primary: #3b82f6;
    --color-success: #10b981;
    /* etc. */
  }
}
```

---

## 🔐 PASSWORD SCREEN

**See previous sections: Authentication Screen (Section 2️⃣1️⃣)**

---

## 📋 DESIGN DELIVERABLES CHECKLIST

Design system should include:
- [ ] Complete component library (buttons, inputs, cards, etc.)
- [ ] Light theme color palette with hex values
- [ ] Dark theme color palette with hex values
- [ ] Typography styles (font family, sizes, weights)
- [ ] Spacing/grid documentation
- [ ] Focus states for all interactive elements
- [ ] Hover/active states for all interactive elements
- [ ] Responsive breakpoints (mobile, tablet, desktop)
- [ ] Animation/transition specs
- [ ] Accessibility guidelines (WCAG AAA)
- [ ] Dark mode implementation specs
- [ ] High-fidelity mockups of all 9 tabs
- [ ] Authentication screen design
- [ ] Mobile/tablet responsive views
- [ ] State variations (loading, error, success, empty)
- [ ] Icon set specifications
- [ ] CSS-in-JS or Tailwind configuration file
- [ ] Storybook component documentation
- [ ] Design tokens export (JSON or CSS)

---

## 🎯 SUMMARY

**Design Goal:** Create a professional, minimalist, ADHD-friendly medical translation interface with:
✅ High visual hierarchy and breathing room  
✅ Clear visual feedback for all interactions  
✅ Intuitive icons and color coding  
✅ Professional medical context  
✅ Light and dark themes  
✅ WCAG AAA accessibility  
✅ Responsive and touch-friendly  
✅ Zero auto-play animations  
✅ Consistent spacing and typography  
✅ Intelligently organized 9-tab workflow  

**Result:** A UI that reduces cognitive load while maintaining professional credibility for medical professionals.

---

**Brief Version:** 2026-06-11  
**Application:** Medical CAT Translator v5.5  
**Status:** Ready for Claude Design implementation  
**Contact:** For questions, refer to app_v55.py and existing components

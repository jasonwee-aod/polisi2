# CSS Selector Tuning Guide

The scraper uses CSS selectors to extract records from listing pages. If you're getting 0 records, the selectors need adjustment.

## How to Find Correct Selectors

### 1. Inspect a Live Page

Open one of your configured URLs in a browser and use Developer Tools:

```bash
# Example: Open in browser
https://www.perpaduan.gov.my/index.php/bm/perkhidmatann/perkhidmatan-lainn/tender-sebuthargaa
```

### 2. Identify Item Container

Right-click on a list item → "Inspect Element". Look for:
- A repeating `<div>` or `<li>` that wraps each record
- It will be a direct child of the main content area

Common patterns:
```html
<div class="item">...</div>
<div class="item-page">...</div>
<li class="result">...</li>
<article class="post">...</article>
```

Update `item_selector` in config:

```yaml
item_selector: "div.item-page"  # Adjust based on what you find
```

### 3. Identify Title Element

Within each item container, find the title/heading:

```html
<div class="item-page">
  <h2>Document Title Here</h2>  <!-- This -->
  ...
</div>
```

Update `title_selector`:

```yaml
title_selector: "h2"  # Can be h2, h3, span.title, etc.
```

### 4. Identify Link Element

Find the `<a>` tag that links to the document:

```html
<div class="item-page">
  <h2>
    <a href="/index.php/bm/document-url">Document Title</a>  <!-- This -->
  </h2>
</div>
```

Update `link_selector`:

```yaml
link_selector: "h2 a"  # Path from item to the link
```

### 5. Identify Date (Optional)

Some pages have publication dates:

```html
<div class="item-page">
  <span class="published">2026-03-09</span>  <!-- This -->
  ...
</div>
```

Update `date_selector`:

```yaml
date_selector: "span.published"
```

## Testing Your Selectors

### 1. Dry Run

```bash
python3 -m src.main \
  --site-config configs/perpaduan.yaml \
  --max-pages 1 \
  --dry-run \
  --log-level DEBUG
```

Check output:
- If `records_written: 0`, selectors aren't matching
- If `records_written: > 0`, selectors are working

### 2. Browser Console Test

In browser Developer Tools console, test your selectors:

```javascript
// Test item_selector
document.querySelectorAll("div.item-page").length  // Should be > 0

// Test title_selector within first item
document.querySelector("div.item-page h2")?.textContent

// Test link_selector
document.querySelector("div.item-page h2 a")?.href
```

### 3. Python Quick Test

```python
from src.crawler import Crawler
from src.scraper import PerpaduanScraper

scraper = PerpaduanScraper("configs/perpaduan.yaml")
fetched = scraper.crawler.fetch("https://...")
soup = scraper.crawler.parse_html(fetched["content"])

# Test item selector
items = soup.select("div.item-page")
print(f"Found {len(items)} items")

# Test title selector on first item
if items:
    title = items[0].select_one("h2")
    print(f"Title: {title.get_text() if title else 'NOT FOUND'}")
```

## Common Issues

### Problem: `records_written: 0`

**Cause**: CSS selectors don't match page structure

**Solution**:
1. Open page in browser
2. Inspect actual HTML
3. Update selectors in config
4. Run dry-run again

### Problem: `title` is empty or wrong

**Cause**: `title_selector` is pointing to wrong element

**Solution**:
1. Right-click on actual title → Inspect
2. Find the element and its CSS class/id
3. Update `title_selector` to match
4. Test in browser console first

### Problem: Links aren't being extracted

**Cause**: `link_selector` isn't finding `<a>` elements

**Solution**:
1. Check if title itself is a link: `<h2><a>Title</a></h2>`
2. Or link is separate: `<h2>Title</h2><a href="...">Read more</a>`
3. Adjust selector accordingly

## Example: Before & After

### Before (0 records)

```yaml
sections:
  - name: "Tender"
    url: "https://www.perpaduan.gov.my/..."
    item_selector: "div.item"      # ❌ Doesn't match
    title_selector: "h3"           # ❌ Wrong tag
    link_selector: "h3 a"
```

### After (Tuned, 45 records)

```yaml
sections:
  - name: "Tender"
    url: "https://www.perpaduan.gov.my/..."
    item_selector: "div.item-page"       # ✅ Matches actual divs
    title_selector: "h2"                 # ✅ Correct tag
    link_selector: "h2 a"                # ✅ Link inside h2
    date_selector: "span.published"      # ✅ Date if present
```

## Selector Syntax

### Basic Selectors

```yaml
# Class selector
item_selector: "div.item-page"         # <div class="item-page">

# ID selector
item_selector: "#main-content"         # <div id="main-content">

# Attribute selector
item_selector: "div[data-type='news']" # <div data-type="news">

# Descendant
title_selector: ".title-text"          # any element with class title-text

# Child combinator
link_selector: "h2 > a"                # direct child <a> of <h2>
```

### Complex Selectors

```yaml
# Multiple classes
item_selector: "div.item.featured"

# Attribute contains
item_selector: "div[class*='item']"    # class contains 'item'

# Nth-child
item_selector: "div:nth-child(odd)"
```

## When to Escalate to Playwright

If after selector tuning you still get 0 records, the page might be JavaScript-rendered:

1. Open page in browser → Inspect → check if content is in HTML (it should be)
2. If HTML is empty and content appears after JS runs, need Playwright
3. This is a future enhancement (not in v0.1)

## Resources

- [CSS Selectors MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_Selectors)
- [BeautifulSoup Selector Docs](https://www.crummy.com/software/BeautifulSoup/bs4/doc/#css-selectors)
- [Browser DevTools](https://developer.mozilla.org/en-US/docs/Learn/Common_questions/Tools_and_setup/What_are_browser_developer_tools)

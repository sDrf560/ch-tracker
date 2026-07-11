"""
Chrome Hearts website tracker.

Scrapes chromehearts.com category pages, compares against saved state,
and sends a push notification (via ntfy.sh) for EVERY change:
  - NEW product listed
  - RESTOCK (was out of stock, now available)
  - SOLD OUT (was available, now out of stock)
  - PRICE change
  - REMOVED product

State is stored in state.json and committed back to the repo by the
GitHub Actions workflow, so each run compares against the last run.
"""

import json
import os
import re
import sys
import time
import urllib.request

BASE = "https://www.chromehearts.com"

# Fallback list if auto-discovery fails
FALLBACK_CATEGORIES = [
    "/baccarat",
    "/scents",
    "/boxers-leggings",
    "/intimates",
    "/socks",
]

# Nav links that aren't shop categories
NON_CATEGORY = {
    "/login", "/cart", "/contact", "/locations", "/magazine",
    "/terms", "/privacy", "/general", "/disclosure", "/search",
    "/account", "/wishlist", "/checkout", "/home",
}


def discover_categories(homepage_html: str) -> list:
    """
    Pull top-level shop category paths out of the homepage navigation.
    Matches single-segment internal links like /socks or /boxers-leggings
    (product pages and static pages end in .html, so they're excluded).
    """
    found = set()
    for m in re.finditer(
        r'href="(?:https?://www\.chromehearts\.com)?(/[a-z0-9\-]+)"', homepage_html
    ):
        path = m.group(1).lower()
        if path not in NON_CATEGORY:
            found.add(path)
    return sorted(found)

STATE_FILE = "state.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_category(html: str, category: str) -> dict:
    """
    Extract products from an SFCC category page.

    Product URLs look like:
      /socks/ch-logo-socks/176354XXXXXX349.html
    We treat the filename (SKU) as the product ID.
    """
    products = {}
    pattern = re.compile(
        re.escape(category) + r"/([a-z0-9\-]+)/([A-Za-z0-9]+)\.html",
    )
    matches = list(pattern.finditer(html))

    for i, match in enumerate(matches):
        slug, sku = match.group(1), match.group(2)
        url = f"{BASE}{category}/{slug}/{sku}.html"

        # Scope this product's chunk: from this link to the next link
        # belonging to a DIFFERENT product, so one product's price /
        # OUT OF STOCK label never bleeds into its neighbour.
        end = len(html)
        for later in matches[i + 1:]:
            if later.group(2) != sku:
                end = later.start()
                break
        chunk = html[match.start():min(end, match.start() + 4000)]

        price_match = re.search(r"\$\s?([\d,]+(?:\.\d{2})?)", chunk)
        price = price_match.group(1).replace(",", "") if price_match else None
        out_of_stock = "OUT OF STOCK" in chunk.upper()

        name = slug.replace("-", " ").upper()

        existing = products.get(sku)
        if existing:
            if existing["price"] is None and price:
                existing["price"] = price
            # OOS if any occurrence's scoped chunk contains the label
            existing["out_of_stock"] = existing["out_of_stock"] or out_of_stock
        else:
            products[sku] = {
                "name": name,
                "url": url,
                "price": price,
                "out_of_stock": out_of_stock,
                "category": category.strip("/"),
            }
    return products


def notify(title: str, message: str, url: str = None, priority: str = "default"):
    if not NTFY_TOPIC:
        print(f"[no NTFY_TOPIC set] {title}: {message}")
        return
    headers = {
        "Title": title.encode("ascii", errors="replace").decode(),
        "Priority": priority,
        "Tags": "shopping_bags",
    }
    if url:
        headers["Click"] = url
    req = urllib.request.Request(
        f"{NTFY_SERVER}/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as exc:  # noqa: BLE001
        print(f"Notification failed: {exc}", file=sys.stderr)


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)


def main():
    old = load_state()
    new = {}
    failures = []

    # Discover categories from the live nav; fall back if that fails
    try:
        homepage = fetch(BASE + "/")
        categories = discover_categories(homepage) or FALLBACK_CATEGORIES
    except Exception as exc:  # noqa: BLE001
        print(f"Homepage fetch failed ({exc}); using fallback list",
              file=sys.stderr)
        categories = FALLBACK_CATEGORIES

    known_cats = set(old.pop("_categories", [])) or \
        {v.get("category") for v in old.values() if isinstance(v, dict)}
    if old:
        for cat in categories:
            if cat.strip("/") not in {str(c).strip("/") for c in known_cats if c}:
                notify(
                    "NEW CATEGORY on chromehearts.com",
                    f"A new shop section appeared: {cat.strip('/')} — "
                    "its products will be tracked from now on.",
                    url=BASE + cat,
                    priority="high",
                )

    for category in categories:
        try:
            html = fetch(BASE + category)
            found = parse_category(html, category)
            print(f"{category}: {len(found)} products")
            if not found:
                # Page loaded but no products parsed — likely a layout
                # change or block page. Treat as failure so we don't
                # falsely report everything as REMOVED.
                failures.append(f"{category}: parsed 0 products")
            else:
                new.update(found)
            time.sleep(2)  # be polite
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{category}: {exc}")
            print(f"FAILED {category}: {exc}", file=sys.stderr)

    if failures and not new:
        # Total failure — don't wipe state, just warn once
        notify(
            "CH tracker error",
            "All category pages failed to load. Site may be blocking "
            "or structure changed.\n" + "\n".join(failures),
            priority="low",
        )
        sys.exit(0)

    if not old:
        # First run: seed state silently, send one confirmation
        new["_categories"] = categories
        save_state(new)
        notify(
            "CH tracker is live",
            f"Now tracking {len(new) - 1} products across "
            f"{len(categories)} categories "
            f"({', '.join(c.strip('/') for c in categories)}). "
            "You'll get a push on every new item, restock, sell-out, "
            "price change, removal, and new category.",
        )
        return

    changes = 0

    # New, restocked, sold out, price changes
    for sku, item in new.items():
        prev = old.get(sku)
        label = f"{item['name']} ({item['category']})"
        price = f"${item['price']}" if item["price"] else "price unknown"

        if prev is None:
            notify(
                f"NEW: {item['name']}",
                f"{label} just appeared — {price}"
                + (" — currently OUT OF STOCK" if item["out_of_stock"] else ""),
                url=item["url"],
                priority="high",
            )
            changes += 1
            continue

        if prev.get("out_of_stock") and not item["out_of_stock"]:
            notify(
                f"RESTOCK: {item['name']}",
                f"{label} is back in stock — {price}",
                url=item["url"],
                priority="high",
            )
            changes += 1

        if not prev.get("out_of_stock") and item["out_of_stock"]:
            notify(
                f"SOLD OUT: {item['name']}",
                f"{label} just went out of stock.",
                url=item["url"],
            )
            changes += 1

        if prev.get("price") and item["price"] and prev["price"] != item["price"]:
            notify(
                f"PRICE CHANGE: {item['name']}",
                f"{label}: ${prev['price']} → ${item['price']}",
                url=item["url"],
            )
            changes += 1

    # Removed products — only if that category loaded successfully
    failed_cats = {f.split(":")[0].strip("/") for f in failures}
    for sku, item in old.items():
        if sku not in new and item.get("category") not in failed_cats:
            notify(
                f"REMOVED: {item['name']}",
                f"{item['name']} ({item['category']}) was removed "
                "from the site.",
                url=item.get("url"),
            )
            changes += 1

    # Preserve items from categories that failed this run
    for sku, item in old.items():
        if sku not in new and item.get("category") in failed_cats:
            new[sku] = item

    new["_categories"] = categories
    save_state(new)
    print(f"Done. {changes} change(s) detected.")


if __name__ == "__main__":
    main()

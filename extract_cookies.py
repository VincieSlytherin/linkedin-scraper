"""Extract LinkedIn cookies from your browser for authentication.

Usage:
    1. Log into LinkedIn in Chrome/Firefox
    2. Run: python extract_cookies.py
    3. Then run: python main.py
"""

import json
import sys


def extract_from_browser():
    """Guide user to manually extract cookies."""
    print("=" * 60)
    print("  LinkedIn Cookie Extractor")
    print("=" * 60)
    print()
    print("To bypass LinkedIn's CHALLENGE error, we need your browser cookies.")
    print()
    print("Steps:")
    print("  1. Open Chrome/Firefox and log into linkedin.com")
    print("  2. Open Developer Tools (F12 or Cmd+Shift+I)")
    print("  3. Go to the 'Application' tab (Chrome) or 'Storage' tab (Firefox)")
    print("  4. Click 'Cookies' → 'https://www.linkedin.com'")
    print("  5. Find and copy the values for these cookies:")
    print("     - li_at")
    print("     - JSESSIONID")
    print()

    li_at = input("Paste the 'li_at' cookie value:\n> ").strip()
    if not li_at:
        print("Error: li_at is required.")
        sys.exit(1)

    jsessionid = input("\nPaste the 'JSESSIONID' cookie value:\n> ").strip()
    jsessionid = jsessionid.strip('"')  # Often wrapped in quotes
    if not jsessionid:
        print("Error: JSESSIONID is required.")
        sys.exit(1)

    cookies = {
        "li_at": li_at,
        "JSESSIONID": jsessionid,
    }

    with open("linkedin_cookies.json", "w") as f:
        json.dump(cookies, f, indent=2)

    print()
    print("Cookies saved to linkedin_cookies.json")
    print("Now run: python main.py")


if __name__ == "__main__":
    extract_from_browser()

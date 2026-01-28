"""Capture screenshots of the map dashboard for the landing page."""
import asyncio
from playwright.async_api import async_playwright

OUTPUT_DIR = "/opt/marine-fishing/frontend/images"
BASE_URL = "http://localhost:8000"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # Full map dashboard - wide shot at 2x for crisp hero background
        page = await browser.new_page(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2
        )
        await page.goto(f"{BASE_URL}/map", wait_until="networkidle", timeout=30000)
        # Wait for map tiles and markers to load
        await page.wait_for_timeout(5000)
        # Hide the loading overlay if still visible
        await page.evaluate("""() => {
            var el = document.getElementById('map-loading');
            if (el) { el.style.display = 'none'; }
        }""")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=f"{OUTPUT_DIR}/map-full.png", type="png")
        print("Captured: map-full.png (2x)")

        # Map zoomed - just the map area
        map_el = await page.query_selector("#map")
        if map_el:
            await map_el.screenshot(path=f"{OUTPUT_DIR}/map-detail.png", type="png")
            print("Captured: map-detail.png (2x)")

        # Weather bar detail
        weather_el = await page.query_selector("#weather-bar")
        if weather_el:
            await weather_el.screenshot(path=f"{OUTPUT_DIR}/weather-bar.png", type="png")
            print("Captured: weather-bar.png (2x)")

        # Mobile view
        page2 = await browser.new_page(
            viewport={"width": 768, "height": 1024},
            device_scale_factor=2
        )
        await page2.goto(f"{BASE_URL}/map", wait_until="networkidle", timeout=30000)
        await page2.wait_for_timeout(5000)
        await page2.evaluate("""() => {
            var el = document.getElementById('map-loading');
            if (el) { el.style.display = 'none'; }
        }""")
        await page2.wait_for_timeout(1000)
        await page2.screenshot(path=f"{OUTPUT_DIR}/map-tablet.png", type="png")
        print("Captured: map-tablet.png (2x)")

        await browser.close()

asyncio.run(main())

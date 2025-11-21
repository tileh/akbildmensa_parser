import io
import logging
import os
import re
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup, Tag
from pyopenmensa.feed import LazyBuilder

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
numeric_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=numeric_level)
log = logging.getLogger("ak")
log.setLevel(numeric_level)


german_weekdays = {
    0: "Montag",
    1: "Dienstag",
    2: "Mittwoch",
    3: "Donnerstag",
    4: "Freitag",
    5: "Samstag",
    6: "Sonntag",
}

MENSA_URL = "https://www.akbild.ac.at/de/universitaet/services/menueplan"

NON_VEGETERIAN = "Nicht Vegetarisch"
VEGETERIAN = "Vegetarisch"
VEGAN = "Vegan"

VEG_PRICE = 6
NON_VEG_PRICE = 7
WOCHENTELLER_PRICE = 8


class Parser:
    def generate_feed(self) -> str:
        log.info(f"Fetching MENSA URL: {MENSA_URL}")
        try:
            r = requests.get(MENSA_URL)
            log.info(f"Fetched {len(r.content)} bytes, status={r.status_code}")
        except Exception as e:
            log.error(f"Failed to fetch MENSA URL {MENSA_URL}: {e}")
            raise

        soup = BeautifulSoup(r.content, "html.parser")

        log.debug("Normalizing parsed HTML (unwrap div/span, normalize <br>)")
        # Normalize the soup early: unwrap noisy containers and normalize <br/>
        # This keeps child nodes (lists, paragraphs) intact while removing
        # extra nesting that breaks parsing for some weekdays (e.g., Freitag).
        self._normalize_soup(soup)
        log.debug("Normalization complete")

        feed = LazyBuilder()

        week_info_str = self._find_weekinfo_str(soup)
        log.info(f"Week info string: {week_info_str}")

        try:
            monday_date = self._get_monday_from_week_info_str(week_info_str)
            log.info(f"Determined monday date: {monday_date}")
        except Exception as e:
            log.warning(f"Could not determine monday from week_info. Falling back to system time: {e}")
            today = date.today()
            monday_date = today - timedelta(days=today.weekday())
            log.info(f"Fallback monday date: {monday_date}")

        menuplan = soup.find(lambda tag: self._get_menuplan_tag(tag))

        try:
            wochenteller = self._parse_wochenteller(menuplan)
            if wochenteller is not None:
                log.info(f"Parsed Wochenteller: {wochenteller.get_text(strip=True)[:120]}")
            else:
                log.info("No Wochenteller found")
        except Exception as e:
            log.warning(f"Could not parse Wochenteller: {e}")

        monday_tag = menuplan.find_next_sibling(
            lambda tag: tag.name == "p" and german_weekdays[0] in tag.get_text()
        )
        weekday_contents = self._split_menu_per_weekday(monday_tag)

        for i, weekday_content in weekday_contents.items():
            current_day_menu = self._find_menu_in_current_weekday_content(
                weekday_content=weekday_content
            )

            current_date = monday_date + timedelta(days=i)
            current_date_str = current_date.strftime("%Y-%m-%d")

            # skip day if e.g. closed
            if current_day_menu is None:
                log.warning(f"menu is None for {current_date_str}")
                continue

            log.info(f"Processing menu for {current_date_str}")
            meal_count = 0
            for meal in current_day_menu.find_all("li"):
                name, category, allergenes = self._parse_mealname(meal.get_text())

                price = NON_VEG_PRICE if category == NON_VEGETERIAN else VEG_PRICE
                prices = {"student": f"{price - 2}.00", "other": f"{price}.00"}

                feed.addMeal(
                    current_date_str, category, name, allergenes, prices=prices
                )
                meal_count += 1
                log.debug(f"Added meal: date={current_date_str} name={name[:60]} category={category}")

            log.info(f"Added {meal_count} meals for {current_date_str}")

            # add wochenteller to each day
            if wochenteller:
                name, category, allergenes = self._parse_mealname(
                    wochenteller.get_text()
                )
                feed.addMeal(
                    current_date_str,
                    f"Wochenteller {category}",
                    name,
                    allergenes,
                    {"other": f"{WOCHENTELLER_PRICE}.00"},
                )

        xml = feed.toXMLFeed()
        log.info("Feed generation complete")
        return xml

    def _parse_wochenteller(self, menuplan: Tag) -> Tag:
        wochenteller_tag = menuplan.find_next_sibling(
            lambda tag: tag.name == "p" and "Wochenteller" in tag.get_text()
        )
        if wochenteller_tag is None:
            log.debug("No Wochenteller <p> tag found")
            return None

        next_tag = wochenteller_tag.find_next_sibling()
        if next_tag is None:
            log.debug("No sibling after Wochenteller tag")
            return None

        meal = next_tag.find("li")
        if meal is None:
            log.debug("No <li> found for Wochenteller")
        return meal

    def _normalize_soup(self, soup: Tag) -> None:
        """Loosens HTML structure to make parsing more robust.

        - Unwraps `div` and `span` tags (removes the tag but keeps children).
        - Replaces `<br>` with newline characters inside the tree.
        - Collapses multiple consecutive newlines inside text nodes.
        """
        # Unwrap structural tags that often only add noise
        for tag_name in ("div", "span"):
            found = list(soup.find_all(tag_name))
            if found:
                log.debug(f"Unwrapping {len(found)} <{tag_name}> tags")
            for t in found:
                try:
                    t.unwrap()
                except Exception as e:
                    log.warning(f"Failed to unwrap <{tag_name}>: {e}")
                    continue

        # Turn <br> into newline characters so text splitting is easier
        brs = list(soup.find_all("br"))
        if brs:
            log.debug(f"Normalizing {len(brs)} <br> tags to newlines")
        for br in brs:
            try:
                br.replace_with("\n")
            except Exception as e:
                log.warning(f"Failed to replace <br>: {e}")
                continue

        # Collapse runs of newlines in text nodes to a single newline
        replaced = 0
        for s in list(soup.find_all(string=True)):
            if s and "\n" in s:
                new = re.sub(r"\n\s*\n+", "\n", s)
                if new != s:
                    s.replace_with(new)
                    replaced += 1
        if replaced:
            log.debug(f"Collapsed newlines in {replaced} text nodes")

    def _extract_items_from_weekday_tags(self, weekday_content: list[Tag]) -> list[str]:
        """Extract candidate meal lines from a list of tags when no <ul>/<li> present.

        Returns a list of cleaned strings representing each meal entry.
        """
        items: list[str] = []
        for tag in weekday_content:
            text = tag.get_text("\n", strip=True)
            if not text:
                continue

            # Split by newline (we normalized <br> to \n earlier) and clean each line
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            for ln in lines:
                # Remove leading bullets/numbers/extra punctuation
                ln = re.sub(r"^[\u2022\-\*\s]*\d*\.*\s*", "", ln)
                ln = re.sub(r"\s+", " ", ln)
                if ln:
                    items.append(ln)

        return items

    def _find_menu_in_current_weekday_content(self, weekday_content: list[Tag]) -> Tag | list[str] | None:
        """Finds the menu for a weekday.

        Returns either:
        - a Tag (usually a <ul>) containing <li> elements, or
        - a list of strings extracted heuristically from br-separated text, or
        - None if nothing found.
        """
        # First try existing logic: find a UL that contains LI elements
        for content in weekday_content:
            ul = content if content.name == "ul" else content.find("ul")
            if ul is None:
                continue

            if (li := ul.find("li")) is None:
                continue

            if li.find("p"):
                return ul

        # Fallback: try to extract items from br/newline separated text
        items = self._extract_items_from_weekday_tags(weekday_content)
        if items:
            # Build a synthetic <ul> with <li> entries so callers can treat uniformly
            soup = BeautifulSoup("<ul></ul>", "html.parser")
            ul = soup.ul
            for it in items:
                li = soup.new_tag("li")
                li.string = it
                ul.append(li)
            return ul

        return None

    

    def _parse_mealname(self, meal: str) -> tuple[str, str, list[str]]:
        # Remove non-breaking spaces and trim
        meal = meal.replace("\xa0", " ").strip()

        # Extract allergen list at the end, e.g., "A, C, G"
        allergen_match = re.search(r"\b([A-Z](?:,\s*[A-Z])*)\s*$", meal)
        allergenes = (
            allergen_match.group(1).replace(" ", "").split(",")
            if allergen_match
            else []
        )

        # Remove the allergen part from the meal string
        if allergen_match:
            meal = meal[: allergen_match.start()].strip()

        # Extract and remove category in parentheses, e.g., "(vegan)"
        category = NON_VEGETERIAN
        category_match = re.search(
            r"\((vegan|vegetarisch|vegan/vegetarisch)\)", meal, re.IGNORECASE
        )
        if category_match:
            label = category_match.group(1).lower()
            category = VEGAN if label.startswith("vegan") else VEGETERIAN
            meal = re.sub(
                r"\s*\(.*?\)", "", meal
            ).strip()  # Remove the category from the meal name

        return meal, category, allergenes

    def _get_monday_from_week_info_str(self, date_str: str) -> date:
        s = date_str.strip()

        # 1) Try explicit numeric format: DD.MM.YYYY
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
        if m:
            day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return date(year, month, day)

        # 2) Try numeric day.month (no year) e.g. "15.11" and a year elsewhere
        m = re.search(r"(\d{1,2})\.(\d{1,2})\b", s)
        if m:
            day, month = int(m.group(1)), int(m.group(2))
            ym = re.search(r"\b(20\d{2})\b", s)
            year = int(ym.group(1)) if ym else date.today().year
            return date(year, month, day)

        # 3) Try textual month names (German)
        months = {
            "januar": 1,
            "februar": 2,
            "märz": 3,
            "maerz": 3,
            "april": 4,
            "mai": 5,
            "juni": 6,
            "juli": 7,
            "august": 8,
            "september": 9,
            "oktober": 10,
            "november": 11,
            "dezember": 12,
        }

        # find any month name present
        month_found = None
        month_pos = None
        for name, num in months.items():
            mname = re.search(r"\b" + re.escape(name) + r"\b", s, re.IGNORECASE)
            if mname:
                month_found = num
                month_pos = mname.start()
                break

        # collect candidate day numbers in text order
        nums = [(m.start(), int(m.group(1))) for m in re.finditer(r"\b(\d{1,2})\b", s)]

        year_m = re.search(r"\b(20\d{2})\b", s)
        year = int(year_m.group(1)) if year_m else date.today().year

        if month_found and nums:
            # prefer the last number that occurs before the month name (start of range)
            before = [n for pos, n in nums if pos < month_pos]
            if before:
                day = before[-1]
            else:
                # fallback: take the first number
                day = nums[0][1]
            try:
                return date(year, month_found, day)
            except Exception as e:
                log.warning(f"Could not build date from textual month: {e}")

        # 4) As a last resort, try to take the first numeric day and assume current month/year
        if nums:
            day = nums[0][1]
            today = date.today()
            try:
                return date(today.year, today.month, day)
            except Exception:
                raise ValueError(f"Could not parse monday from week info: '{date_str}'")

        # Nothing matched
        raise ValueError(f"Could not parse monday from week info: '{date_str}'")

    def _split_menu_per_weekday(self, tag: Tag) -> dict[int, list[Tag]]:
        result = {}
        all_siblings = tag.find_next_siblings()
        current_tags = []
        weekday_index = 0
        num_weekdays = len(german_weekdays)

        for sibling in all_siblings:
            sibling_text = sibling.get_text(strip=True)

            # Check if the next weekday appears in the sibling
            if (
                weekday_index + 1 < num_weekdays
                and german_weekdays[weekday_index + 1] in sibling_text
            ):
                # Store accumulated tags for current weekday
                result[weekday_index] = current_tags
                current_tags = []
                weekday_index += 1
            else:
                current_tags.append(sibling)

        # Add the remaining tags to friday
        if current_tags:
            result[weekday_index] = current_tags

        return result

    def _get_menuplan_tag(self, currentTag: Tag) -> Tag:
        return currentTag.name == "h2" and "Menüplan" in currentTag.get_text()

    def _find_weekinfo_str(self, soup) -> str:
        p = soup.find(lambda tag: self._get_menuplan_tag(tag)).find_next_sibling("p")

        strong_tag = p.find("strong")
        return strong_tag.get_text() if strong_tag else p.get_text()


if __name__ == "__main__":
    log.info("Running parser")
    os.makedirs("feed", exist_ok=True)
    feed = Parser().generate_feed()
    with io.open("feed/akbild.xml", "w", encoding="utf8", newline="\n") as f:
        f.write(feed)

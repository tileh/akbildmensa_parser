import io
import logging
import os
import re
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup, Tag
from pyopenmensa.feed import LazyBuilder

logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO)
log = logging.getLogger("ak")


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

NON_VEG_PRICE = 7
VEG_PRICE = 6


class Parser:
    def generate_feed(self) -> str:
        r = requests.get(MENSA_URL)
        soup = BeautifulSoup(r.content, "html.parser")
        feed = LazyBuilder()

        week_info_str = self._find_weekinfo_str(soup)

        try:
            monday_date = self._get_monday_from_week_info_str(week_info_str)
        except Exception as e:
            log.warning(
                f"Could not determine monday from week_info. Falling back to system time: {e}"
            )
            today = date.today()
            monday_date = today - timedelta(days=today.weekday())

        monday_tag = soup.find(
            lambda tag: self._get_menuplan_tag(tag)
        ).find_next_sibling(
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

            for meal in current_day_menu.find_all("li"):
                name, category, allergenes = self._parse_mealname(meal.get_text())

                price = NON_VEG_PRICE if category == NON_VEGETERIAN else VEG_PRICE
                prices = {"student": f"{price - 2}.00", "other": f"{price}.00"}

                feed.addMeal(
                    current_date_str, category, name, allergenes, prices=prices
                )

        return feed.toXMLFeed()

    def _find_menu_in_current_weekday_content(self, weekday_content: list[Tag]) -> Tag:
        for content in weekday_content:
            ul = content if content.name == "ul" else content.find("ul")
            if ul is None:
                continue

            if (li := ul.find("li")) is None:
                continue

            if li.find("p"):
                return ul

        return ul

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
        start_part = date_str.split("bis")[0].strip()
        str_split_by_fullstop = date_str.split(".")
        year = str_split_by_fullstop[len(str_split_by_fullstop) - 1]
        date_str = start_part.split()[-1] + year
        return datetime.strptime(date_str, "%d.%m.%Y").date()

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

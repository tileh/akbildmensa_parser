import io
import logging
import os
import re
from datetime import date, timedelta

import dateparser
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

VEG_PRICE = 6
NON_VEG_PRICE = 7
WOCHENTELLER_PRICE = 8


class Parser:
    def generate_feed(self, fetch_date: date) -> str:
        r = requests.get(MENSA_URL)
        soup = BeautifulSoup(r.content, "html.parser")
        soup = self._unstir_the_soup(soup)
        feed = LazyBuilder()

        menuplan = soup.find(lambda tag: self._get_menuplan_tag(tag))

        monday_date = self._calculate_week_start_date(fetch_date, menuplan)

        try:
            wochenteller = self._parse_wochenteller(menuplan)
        except Exception as e:
            log.warning(f"Could not parse Wochenteller: {e}")

        monday_tag = menuplan.find_next_sibling(
            lambda tag: tag.name == "p" and german_weekdays[0] in tag.get_text()
        )
        weekday_contents = self._split_menu_per_weekday(monday_tag)

        for i, weekday_content in weekday_contents.items():
            current_day_menu = None
            try:
                current_day_menu = self._find_menu_in_current_weekday_content(
                    weekday_content=weekday_content
                )
            except Exception as e:
                log.warning(f"Could not find menu in weekday_content: {e}")

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

        return feed.toXMLFeed()

    def _calculate_week_start_date(self, fetch_date, menuplan) -> date:
        """
        Tries to parse the week start date (Monday) from the menuplan.
        If it fails, it falls back to calculating the Monday of the fetch_date's week.
        """

        try:
            menu_period = menuplan.find_next_sibling("p").get_text()
            menu_period_start_date = menu_period.split("bis")[0].strip()
            parsed_start_date = dateparser.parse(
                menu_period_start_date, languages=["de"], date_formats=["%a, %d.%m"]
            ).date()

            # If the parsed date is more than 7 days in the future, it must likely belong to the previous year
            # For example, when you parse in January, the menuplan might still show "Mo, 15. Dezember bis Fr, 19. Dezember"
            # as the last menuplan of the previous year. In this case, we adjust the year accordingly.
            if parsed_start_date > fetch_date + timedelta(days=7):
                parsed_start_date = parsed_start_date.replace(year=fetch_date.year - 1)

            if parsed_start_date.weekday() != 0:
                raise Exception(
                    f"Parsed start date is not a Monday: {parsed_start_date}"
                )

            monday_date = parsed_start_date
        except Exception as e:
            log.warning(
                f"Could not parse weekinfo string: {e}. Falling back to fetch_date."
            )
            monday_date = fetch_date - timedelta(days=fetch_date.weekday())
        return monday_date

    def _parse_wochenteller(self, menuplan: Tag) -> Tag:
        wochenteller_tag = menuplan.find_next_sibling(
            lambda tag: tag.name == "p" and "Wochenteller" in tag.get_text()
        )
        meal = wochenteller_tag.find_next_sibling().find("li")
        return meal

    def _find_menu_in_current_weekday_content(self, weekday_content: list[Tag]) -> Tag:
        for content in weekday_content:
            ul = content if content.name == "ul" else content.find("ul")
            if ul is None:
                continue

            if (li := ul.find("li")) is None:
                continue

            if li.find("p"):
                return ul

        raise ValueError("Could not find ul")

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

    def _unstir_the_soup(self, soup):
        # remove <strong> and <p> tags that have no visible/text content
        for tag in soup.find_all(["strong", "p"]):
            if tag.get_text(strip=True):
                continue
            else:
                tag.decompose()
        # finally unwrap all divs
        for div in soup.find_all("div"):
            div.unwrap()

        return soup


if __name__ == "__main__":
    log.info("Running parser")
    os.makedirs("feed", exist_ok=True)

    fetch_date = date.today()
    # If today is Saturday or Sunday, use the next Monday
    if fetch_date.weekday() >= 5:
        fetch_date += timedelta(days=(7 - fetch_date.weekday()))

    feed = Parser().generate_feed(fetch_date)
    with io.open("feed/akbild.xml", "w", encoding="utf8", newline="\n") as f:
        f.write(feed)

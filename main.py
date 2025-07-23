import re
import os
import io
from bs4 import BeautifulSoup
import requests
import re
from pyopenmensa.feed import LazyBuilder
from datetime import date, datetime, timedelta



german_weekdays = {
    0: "Montag",
    1: "Dienstag",
    2: "Mittwoch",
    3: "Donnerstag",
    4: "Freitag",
    5: "Samstag",
    6: "Sonntag"
}

MENSA_URL = "https://www.akbild.ac.at/de/universitaet/services/menueplan"

NON_VEGETERIAN = "nicht vegetarisch"
VEGETERIAN = "vegetarisch"
VEGAN = "vegan"

NON_VEG_PRICE = 7
VEG_PRICE = 6


class Parser:
    def generate_feed(self) -> str:
        r = requests.get(MENSA_URL)
        soup = BeautifulSoup(r.content, 'html.parser')
        feed = LazyBuilder()

        week_info_str = (
            soup
            .find('h2', string="Menüplan")
            .find_next_sibling('p')
            .find('strong')
            .get_text()
        )

        # try extracting string from website, else fallback to current week
        try:
            monday_date = self.get_monday_from_week_info_str(week_info_str)
        except:
            today = date.today()
            monday_date = today - timedelta(days=today.weekday())
 
        for i, weekday in enumerate(german_weekdays):
            
            current_day_menu = self.parse_menu_for_weekday(soup, i)

            #
            if current_day_menu is None:
                continue

            current_date = monday_date + timedelta(days=i)
            current_date_str = current_date.strftime("%Y-%m-%d")


            

            for j, meal in enumerate(current_day_menu.find_all('li')): 
                name, category = self.parse_mealname(meal.get_text())

                price = NON_VEG_PRICE if category == NON_VEGETERIAN else VEG_PRICE

                prices = {
                    "student": str(price - 2) + ".00",
                    "other": str(price) + ".00"
                }

                feed.addMeal(
                    current_date_str,
                    category,
                    name,
                    prices=prices
                )

        return feed.toXMLFeed()


    def parse_menu_for_weekday(self, response: BeautifulSoup, weekday: int) -> list:

        wochentag = german_weekdays[weekday]

        current_sibling = (
            response
            .find('h2', string="Menüplan")
            .find_next_sibling("p", string=wochentag)
        )

        # is None for weekends or holidays
        if current_sibling is None:
            return None
        
        return current_sibling.find_next_sibling("ul")

    def parse_mealname(self, meal: str) -> tuple:
        # Remove non-breaking spaces and trim
        meal = meal.replace("\xa0", " ").strip()
        meal_name = re.sub(r'\s*\([^)]*\)\s*$', '', meal).strip()

        category = NON_VEGETERIAN
        
        if VEGAN in meal:
            category = VEGAN
        elif VEGETERIAN in meal:
            category = VEGETERIAN
        
        return meal_name, category
        
    
    def get_monday_from_week_info_str(self, date_str: str) -> date:
        start_part = date_str.split("bis")[0].strip()
        str_split_by_fullstop = date_str.split(".")
        year = str_split_by_fullstop[len(str_split_by_fullstop) - 1]
        date_str = start_part.split()[-1] + year
        return datetime.strptime(date_str, "%d.%m.%Y").date()
    
if __name__ == "__main__":
    os.makedirs("feed", exist_ok=True)
    parser = Parser()
    feed = parser.generate_feed()
    with io.open("feed/akbild.xml", "w", encoding="utf8", newline="\n") as f:
        f.write(feed)
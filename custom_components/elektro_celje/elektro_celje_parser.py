"""Service for Elektro Celje component."""
import logging
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from bs4 import BeautifulSoup
from datetime import datetime
import feedparser

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.elektro-celje.si/si/rss.ashx?k="

@dataclass
class ElektroCeljeData:
    success: bool
    published_date: str
    working_date: str
    start_date: datetime
    end_date: datetime
    description: str

class ElektroCeljeParser:
    """Service for fetching data from Elektro Celje."""

    def __init__(self, region):
        """Initialize the ElektroCeljeParser."""
        self._region = region
        self._base_url = BASE_URL

    def fetch_data(self, search_station):
        """Fetch and parse data from the Elektro Celje RSS feed."""
        try:
            # Construct the RSS feed URL
            rss_url = f"{self._base_url}{self._region.lower()}"
            _LOGGER.debug(f"Fetching RSS feed from: {rss_url}")

            # Fetch and parse the RSS feed
            feed = feedparser.parse(rss_url)

            # Search for the given station in the description of each item
            for item in feed.entries:
                if search_station.lower() in item.summary.lower():

                    _LOGGER.info(f"Search parameter '{search_station}' found in RSS feed.")
                    _LOGGER.debug(f"Item: {item}")

                    # If found, extract the published date
                    published_date_str = item.get("published", "")
                    published_date = self.parse_published_date(published_date_str)

                    # Decode HTML-encoded text in description
                    decoded_description = unescape(item.summary)
                
                    # Extract text inside the UL tag with class name 'dates-list'
                    dates_list_text = self.extract_dates_list_text(decoded_description)

                    # Prefix the variable with the specified text
                    working_date = f"Izpad elektrike {dates_list_text}" if dates_list_text else None

                    # Extract start and end dates from the working_date
                    start_date, end_date = self.extract_dates(dates_list_text)

                    # Return encapsulated data as an object
                    return ElektroCeljeData(
                        success=True,
                        published_date=published_date,
                        working_date=working_date,
                        start_date=start_date,
                        end_date=end_date,
                        description=decoded_description
                    )

            # Station not found in any items, indicating no problem
            _LOGGER.info(f"Search parameter '{search_station}' not found in RSS feed.")
            return ElektroCeljeData(
                success=False,
                published_date="",
                working_date="",
                start_date=None,
                end_date=None,
                description=""
            )

        except Exception as e:
            _LOGGER.error(f"Error fetching or parsing data: {e}")
            return ElektroCeljeData(
                success=False,
                published_date="",
                working_date="",
                start_date=None,
                end_date=None,
                description=""
            )

    def parse_published_date(self, date_str):
        """Parse published date string into a datetime object."""
        try:
            _LOGGER.debug(f"Date to be parsed: {date_str}")
            return datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S").isoformat()
        except ValueError as e:
            _LOGGER.warning(f"Date parse error: {e}")
            return None

    def extract_dates_list_text(self, decoded_description):
        """Extract text inside the UL tag with class name 'dates-list' using BeautifulSoup."""
        soup = BeautifulSoup(decoded_description, 'html.parser')
        ul_tag = soup.find('ul', class_='dates-list')
        if ul_tag:
            li_tag = ul_tag.find('li')
            if li_tag:
                return li_tag.get_text(strip=True)

        return None

    def extract_dates(self, description: str):
        import re
        from datetime import datetime

        _LOGGER.debug(f"Dates to be parsed: {description}")
        # Regex to extract the date and time
        date_regex = re.compile(r"(\d{1,2}\. *\w+ \d{4})")
        time_regex = re.compile(r"(\d{2}:\d{2})")

        # Slovenian month replacements
        slovenian_months = {
            "januarja": "january",
            "februarja": "february",
            "marca": "march",
            "aprila": "april",
            "maja": "may",
            "junija": "june",
            "julija": "july",
            "avgusta": "august",
            "septembra": "september",
            "oktobra": "october",
            "novembra": "november",
            "decembra": "december"
        }

        # Function to replace Slovenian month with English equivalent
        def replace_slovenian_months(date_str):
            for slo_month, eng_month in slovenian_months.items():
                if slo_month in date_str:
                    return date_str.replace(slo_month, eng_month)
            return date_str

        # Extract date and time
        date_match = date_regex.search(description)
        time_matches = time_regex.findall(description)

        # Parse the date
        _LOGGER.debug(f"Date match: {date_match}")
        if date_match:
            extracted_date = date_match.group(0)
            extracted_date = replace_slovenian_months(extracted_date)
            extracted_date = datetime.strptime(extracted_date, "%d. %B %Y")

        # Parse the times
        if time_matches:
            start_time = time_matches[0]
            end_time = time_matches[1]

        # Convert the start and end times
        start_datetime = datetime.combine(extracted_date, datetime.strptime(start_time, "%H:%M").time())
        end_datetime = datetime.combine(extracted_date, datetime.strptime(end_time, "%H:%M").time())

        return start_datetime, end_datetime

# Create an instance of ElektroCeljeParser with a region
#elektro_celje_parser = ElektroCeljeParser("default")

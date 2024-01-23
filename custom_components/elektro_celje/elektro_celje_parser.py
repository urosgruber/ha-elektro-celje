"""Service for Elektro Celje component."""
import logging
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from bs4 import BeautifulSoup
import feedparser

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.elektro-celje.si/si/rss.ashx?k="

@dataclass
class ElektroCeljeData:
    success: bool
    published_date: str
    working_date: str
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

                    # Return encapsulated data as an object
                    return ElektroCeljeData(
                        success=True,
                        published_date=published_date,
                        working_date=working_date,
                        description=decoded_description
                    )
                    #Return all processed variables
                    return True, published_date, izpad_text, decoded_description

            # Station not found in any items, indicating no problem
            _LOGGER.info(f"Search parameter '{search_station}' not found in RSS feed.")
            return ElektroCeljeData(
                success=False,
                published_date="",
                working_date="",
                description=""
            )

        except Exception as e:
            _LOGGER.error(f"Error fetching or parsing data: {e}")
            return ElektroCeljeData(
                success=False,
                published_date="",
                working_date="",
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

# Create an instance of ElektroCeljeParser with a region
#elektro_celje_parser = ElektroCeljeParser("default")

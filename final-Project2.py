import functools
from abc import ABC, abstractmethod
from datetime import datetime

import requests


API_BASE = "https://api.frankfurter.dev/v1"


def current_time_str() -> str:
    """Return the local time as a string formatted 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_action(func):
    """
    - Wraps each action in try/except
    - Prevents the whole program from crashing
    - Logs errors if a logger is available
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except KeyboardInterrupt:
            print("\n[i] Operation cancelled by user.\n")
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.log(f"User cancelled operation in {func.__name__} with Ctrl+C.")
        except Exception as exc:
            print(f"[!] Something went wrong in {func.__name__}: {exc}\n")
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.log(f"Error in {func.__name__}: {exc}")
    return wrapper


class SessionLogger:
    def __init__(self, filename: str = "currency_app.log") -> None:
        self.filename = filename
        self._file = None

    def __enter__(self) -> "SessionLogger":
        self._file = open(self.filename, "ab")
        self.log("=== New session started ===")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.log("Session ended normally.")
        else:
            self.log(f"Session ended with error {exc_type.__name__}: {exc}")
        if self._file is not None:
            self._file.close()
            self._file = None

    def log(self, message: str) -> None:
        if self._file is None:
            return
        timestamp = current_time_str()
        line = f"[{timestamp}] {message}\n"
        encoded_line: bytes = line.encode("utf-8")
        self._file.write(encoded_line)
        self._file.flush()


class RateProvider(ABC):
    @abstractmethod
    def fetch_latest_rate(
        self,
        base_currency_code: str,
        target_currency_code: str
    ) -> tuple[float, str]:
        ...

    @abstractmethod
    def fetch_rate_on_date(
        self,
        base_currency_code: str,
        target_currency_code: str,
        date_text: str
    ) -> tuple[float, str]:
        ...


class CurrencyAPIClient(RateProvider):
    def __init__(self, base_url: str = API_BASE) -> None:
        self.base_url = base_url

    def http_get_json(
        self,
        endpoint_path: str,
        query_params: dict[str, ] = None
    ) -> dict[str, ]:
        """
        Perform HTTP GET to the Frankfurter API and return parsed JSON.

        Return None on any network / HTTP / JSON error.
        """
        try:
            response = requests.get(
                f"{self.base_url}{endpoint_path}",
                params=query_params,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.Timeout:
            print("[!] Request timed out. Please check your internet connection.")
        except requests.RequestException as e:
            print(f"[!] HTTP error: {e}")
        except ValueError:
            print("[!] Failed to decode JSON from API.")
        return None

    def fetch_latest_rate(
        self,
        base_currency_code: str,
        target_currency_code: str
    ) -> tuple[float, str]:
        """Return (rate, date) for the latest business day using `/latest`."""
        params_for_api = {
            "base": base_currency_code,
            "symbols": target_currency_code
        }
        data = self.http_get_json("/latest", query_params=params_for_api)
        if (
            data is None
            or "rates" not in data
            or target_currency_code not in data["rates"]
        ):
            return None, None
        return float(data["rates"][target_currency_code]), data.get("date", "")

    def fetch_rate_on_date(
        self,
        base_currency_code: str,
        target_currency_code: str,
        date_text: str
    ) -> tuple[float, str]:
        """Return (rate, date) for a specific business day using `/{YYYY-MM-DD}`."""
        params_for_api = {
            "base": base_currency_code,
            "symbols": target_currency_code
        }
        data = self.http_get_json(f"/{date_text}", query_params=params_for_api)
        if (
            data is None
            or "rates" not in data
            or target_currency_code not in data["rates"]
        ):
            return None, None
        return float(data["rates"][target_currency_code]), data.get("date", date_text)


class CurrencyConverter:
    def __init__(
        self,
        api_client: "RateProvider" = None,
        logger: "SessionLogger" = None
    ) -> None:
        self.api_client = api_client or CurrencyAPIClient()
        self.logger = logger
        self.base_currency: str = "USD"
        self.currencies: dict[str, str] = {}
        self.load_supported_currencies()

    # ---------- Validation / Utility ----------

    @staticmethod
    def is_number_str(number_text: str) -> bool:
        """Return True if `number_text` looks like a (possibly signed) decimal number."""
        text_to_check = number_text.strip()
        if text_to_check == "":
            return False

        # Optional sign
        if text_to_check[0] in "+-":
            text_to_check = text_to_check[1:]
            if text_to_check == "":
                return False

        # At most one decimal point
        if text_to_check.count(".") > 1:
            return False

        if not any(ch.isdigit() for ch in text_to_check):
            return False

        parts = text_to_check.split(".")
        if len(parts) == 1:
            return parts[0].isdigit()

        left, right = parts
        left_ok = (left == "") or left.isdigit()
        right_ok = (right == "") or right.isdigit()
        return left_ok and right_ok

    @staticmethod
    def parse_amount(amount_text: str) -> float:
        """Convert a validated numeric string into a float."""
        return float(amount_text.strip())

    @staticmethod
    def is_valid_date_yyyy_mm_dd(date_text: str) -> bool:
        """Return True if `date_text` is a valid calendar date in 'YYYY-MM-DD' format."""
        text_to_check = date_text.strip()
        parts = text_to_check.split("-")
        if len(parts) != 3:
            return False

        year_text, month_text, day_text = parts
        if not (
            len(year_text) == 4
            and len(month_text) == 2
            and len(day_text) == 2
        ):
            return False

        if not (year_text.isdigit() and month_text.isdigit() and day_text.isdigit()):
            return False

        year = int(year_text)
        month = int(month_text)
        day = int(day_text)

        if month < 1 or month > 12:
            return False

        is_leap_year = (year % 400 == 0) or (year % 4 == 0 and year % 100 != 0)
        feb_days = 29 if is_leap_year else 28

        month_days = [31, feb_days, 31, 30, 31, 30,
                      31, 31, 30, 31, 30, 31]

        return 1 <= day <= month_days[month - 1]

    def _prompt_currency_code(
        self,
        prompt: str,
        allow_empty: bool = False,
        default: str = None,
        treat_empty_as_cancel: bool = False
    ) -> str:
        """
        Prompt the user for a currency code with up to 3 attempts.
        - If allow_empty and default is provided: pressing Enter uses the default.
        - If treat_empty_as_cancel: pressing Enter cancels the action.
        """
        attempts = 0
        while attempts < 3:
            code = input(prompt).strip().upper()
            if code == "":
                if allow_empty and default is not None:
                    return default
                if treat_empty_as_cancel:
                    print("[i] Cancelled. Returning to main menu.\n")
                    return None
                print("[!] Currency code cannot be empty.")
                attempts += 1
                continue

            if self.is_valid_currency_code(code):
                return code

            print("[!] Invalid currency code.")
            attempts += 1

        print("[!] Too many invalid attempts. Returning to main menu.\n")
        return None

    def _prompt_amount(self, prompt: str) -> float:
        """Prompt the user for an amount (non-negative), with up to 3 attempts."""
        attempts = 0
        while attempts < 3:
            text = input(prompt).strip()
            if text == "":
                print("[!] Amount cannot be empty.")
                attempts += 1
                continue
            if not self.is_number_str(text):
                print("[!] Please enter a valid numeric amount (e.g., 100 or 123.45).")
                attempts += 1
                continue

            value = self.parse_amount(text)
            if value < 0:
                print("[!] Amount must be non-negative.")
                attempts += 1
                continue
            return value

        print("[!] Too many invalid attempts. Returning to main menu.\n")
        return None

    def _prompt_date_or_latest(self, prompt: str) -> str:
        """
        Prompt the user for a date.
        - Enter -> use latest rate (return "")
        - Invalid format -> retry up to 3 times
        - On too many invalid attempts -> return None to cancel the action
        """
        attempts = 0
        while attempts < 3:
            text = input(prompt).strip()
            if text == "":
                return ""  # latest
            if self.is_valid_date_yyyy_mm_dd(text):
                return text
            print("[!] Invalid date format. Please use YYYY-MM-DD (e.g., 2025-11-05).")
            attempts += 1

        print("[!] Too many invalid attempts. Returning to main menu.\n")
        return None

    # ---------- State & Data ----------

    def load_supported_currencies(self) -> None:
        """Load supported currencies and store them in self.currencies."""
        data_from_api = self.api_client.http_get_json("/currencies")
        if data_from_api is not None:
            self.currencies = dict(sorted(data_from_api.items()))
        else:
            print("[i] Cannot fetch currencies from API, using fallback list.")
            self.currencies = {
                "USD": "US Dollar",
                "EUR": "Euro",
                "THB": "Thai Baht",
                "JPY": "Japanese Yen",
                "GBP": "British Pound",
            }

    def is_valid_currency_code(self, currency_code_text: str) -> bool:
        """Return True if the code is a known 3-letter currency code."""
        if currency_code_text is None:
            return False
        code = currency_code_text.strip().upper()
        return (
            len(code) == 3
            and code.isalpha()
            and code in self.currencies
        )

    # ---------- Iterator / Generator ----------

    def iter_currencies(self) -> tuple[str, str]:
        """
        Generator over currencies.
        Used in list_supported_currencies().
        """
        for item in self.currencies.items():
            yield item

    # ---------- CLI Actions ----------

    @safe_action
    def list_supported_currencies(self) -> None:
        """Print all supported currencies (no paging)."""
        if not self.currencies:
            self.load_supported_currencies()

        total = len(self.currencies)
        if total == 0:
            print("\n[!] No currencies loaded.\n")
            return

        print(f"\n[Supported Currencies] ({total} codes)")
        if self.logger is not None:
            self.logger.log("User listed supported currencies.")

        for code, name in self.iter_currencies():
            print(f"- {code}: {name}")
        print()

    @safe_action
    def set_base_currency(self) -> None:
        """Let the user change the base currency (3 attempts for invalid input)."""
        if not self.currencies:
            self.load_supported_currencies()

        print(f"\nCurrent base currency: {self.base_currency}")
        # Enter = cancel
        code = self._prompt_currency_code(
            "Enter new base currency code (3 letters, e.g., USD) or press Enter to cancel: ",
            allow_empty=False,
            default=None,
            treat_empty_as_cancel=True,
        )
        if code is None:
            return

        self.base_currency = code
        print(f"[✓] Base currency set to {self.base_currency}\n")
        if self.logger is not None:
            self.logger.log(f"Base currency changed to {self.base_currency}")

    @safe_action
    def get_exchange_rate_cli(self) -> None:
        """
        Interactive flow: ask for base/target currency + optional date,
        then display the rate. Each field allows up to 3 invalid attempts.
        """
        if not self.currencies:
            self.load_supported_currencies()

        print(f"\nCurrent base currency: {self.base_currency}")

        # Base currency (Enter = use current base)
        base_code = self._prompt_currency_code(
            "Enter base currency (3 letters) or press Enter to use current base: ",
            allow_empty=True,
            default=self.base_currency,
            treat_empty_as_cancel=False,
        )
        if base_code is None:
            return

        # Target currency
        target_code = self._prompt_currency_code(
            "Enter target currency (3 letters, e.g., THB): ",
            allow_empty=False,
            default=None,
            treat_empty_as_cancel=False,
        )
        if target_code is None:
            return

        # Date
        date_text = self._prompt_date_or_latest(
            "\nEnter date [YYYY-MM-DD] for historical rate, or press Enter for latest: "
        )
        if date_text is None:
            return

        if date_text == "":
            rate, api_date = self.api_client.fetch_latest_rate(base_code, target_code)
        else:
            rate, api_date = self.api_client.fetch_rate_on_date(
                base_code, target_code, date_text
            )

        if rate is None:
            print("[!] Failed to retrieve rate.\n")
            return

        if self.logger is not None:
            self.logger.log(
                f"Rate checked: {base_code}->{target_code} (date={api_date}, rate={rate})"
            )

        result = f"[Rate] {base_code} → {target_code} = {rate:,.6f}  (date={api_date})"
        border = "=" * (len(result) + 2)
        print()
        print(border)
        print("", result)
        print(border)
        print()

    @safe_action
    def convert_currency_amount(self) -> None:
        """
        Interactive flow: convert an amount from one currency to another.
        Each input field (source, target, amount, date) allows up to 3 invalid attempts.
        """
        if not self.currencies:
            self.load_supported_currencies()

        print(f"\nCurrent base currency: {self.base_currency}")

        # Source currency (Enter = use base)
        source_currency_code = self._prompt_currency_code(
            "Enter source currency (3 letters) or press Enter to use base: ",
            allow_empty=True,
            default=self.base_currency,
            treat_empty_as_cancel=False,
        )
        if source_currency_code is None:
            return

        # Target currency
        target_currency_code = self._prompt_currency_code(
            "Enter target currency (3 letters): ",
            allow_empty=False,
            default=None,
            treat_empty_as_cancel=False,
        )
        if target_currency_code is None:
            return

        if source_currency_code == target_currency_code:
            print("[i] Same currency → amount unchanged.\n")
            return

        # Amount
        amount = self._prompt_amount(
            "Amount (non-negative number, e.g., 100 or 123.45): "
        )
        if amount is None:
            return

        # Date
        date_text = self._prompt_date_or_latest(
            "Enter date [YYYY-MM-DD] for historical rate, or press Enter for latest: "
        )
        if date_text is None:
            return

        if date_text == "":
            rate, rate_date = self.api_client.fetch_latest_rate(
                source_currency_code, target_currency_code
            )
        else:
            rate, rate_date = self.api_client.fetch_rate_on_date(
                source_currency_code, target_currency_code, date_text
            )

        if rate is None:
            print("[!] Failed to retrieve rate.\n")
            return

        converted_amount = amount * rate

        if self.logger is not None:
            self.logger.log(
                f"Converted {amount} {source_currency_code} "
                f"to {converted_amount} {target_currency_code} "
                f"(rate={rate}, date={rate_date})"
            )

        result = (
            f"[Result] {amount:,.2f} {source_currency_code} → "
            f"{converted_amount:,.2f} {target_currency_code}  "
            f"(rate={rate:,.6f}, date={rate_date})"
        )

        border = "=" * (len(result) + 2)
        print()
        print(border)
        print("", result)
        print(border)
        print()

    # ---------- UI / Main loop ----------

    def show_option(self) -> None:
        """Display current time, base currency, and menu options."""
        print(f"Time (local): {current_time_str()}")
        print(f"Base currency: {self.base_currency}")
        print(
            """
[1] List currencies     
[2] Convert amount      
[3] Show rate           
[4] Change base currency
[9] Show menu again     
[0] Quit
"""
        )

    def run(self) -> None:
        """Entry point: show banner+menu, and dispatch commands in a loop."""
        print(
            """
╻ ╻┏━╸╻  ┏━╸┏━┓┏┳┓┏━╸   ╺┳╸┏━┓   ┏━╸╻ ╻┏━┓┏━┓┏━╸┏┓╻┏━╸╻ ╻   ┏━╸┏━┓┏┓╻╻ ╻┏━╸┏━╸╺┳╸┏━╸┏━╓
┃╻┃┣╸ ┃  ┃  ┃ ┃┃┃┃┣╸     ┃ ┃ ┃   ┃  ┃ ┃┣┳┛┣┳┛┣╸ ┃┗┫┃  ┗┳┛   ┃  ┃ ┃┃┗┫┃┏┛┣╸ ┣┳┛ ┃ ┣╸ ┣┳┛
┗┻┛┗━╸┗━╸┗━╸┗━┛╹ ╹┗━╸    ╹ ┗━┛   ┗━╸┗━┛╹┗╸╹┗╸┗━╸╹ ╹┗━╸ ╹    ┗━╸┗━┛╹ ╹┗┛ ┗━╸╹┗╸ ╹ ┗━╸╹┗╸
"""
        )
        self.show_option()

        while True:
            try:
                cmd = input("Select option (0=Quit, 9=Menu): ").strip()
            except KeyboardInterrupt:
                print("\nBye!")
                if self.logger is not None:
                    self.logger.log("User terminated app with Ctrl+C in main loop.")
                break

            if cmd == "1":
                self.list_supported_currencies()
            elif cmd == "2":
                self.convert_currency_amount()
            elif cmd == "3":
                self.get_exchange_rate_cli()
            elif cmd == "4":
                self.set_base_currency()
            elif cmd == "9":
                self.show_option()
            elif cmd == "0":
                print("Bye!")
                if self.logger is not None:
                    self.logger.log("User selected Quit.")
                break
            elif cmd == "":
                continue
            else:
                print("[!] Unknown option. Press 9 to show the menu.\n")


def main() -> None:
    """Program entry point."""
    with SessionLogger("currency_app.log") as logger:
        app = CurrencyConverter(logger=logger)
        app.run()


main()
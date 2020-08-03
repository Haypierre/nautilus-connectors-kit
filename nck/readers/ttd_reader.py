# License as published by the Free Software Foundation; either
# version 3 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import logging
import click
from click import ClickException
import requests
from datetime import timedelta
from tenacity import retry, wait_exponential, stop_after_delay

from nck.utils.args import extract_args
from nck.commands.command import processor
from nck.readers.reader import Reader
from nck.streams.normalized_json_stream import NormalizedJSONStream
from nck.helpers.ttd_helper import (
    API_HOST,
    API_ENDPOINTS,
    DEFAULT_REPORT_SCHEDULE_ARGS,
    DEFAULT_PAGING_ARGS,
    build_headers,
    format_date,
)
from nck.utils.text import get_report_generator_from_flat_file


@click.command(name="read_ttd")
@click.option("--ttd-login", required=True, help="Login of your API account")
@click.option("--ttd-password", required=True, help="Password of your API account")
@click.option(
    "--ttd-advertiser-id",
    required=True,
    multiple=True,
    help="Advertiser Ids for which report data should be fetched",
)
@click.option(
    "--ttd-report-template-name",
    required=True,
    help="Exact name of the Report Template to request. Existing Report Templates "
    "can be found within the MyReports section of The Trade Desk UI.",
)
@click.option(
    "--ttd-report-schedule-name",
    required=True,
    help="Name of the Report Schedule to create.",
)
@click.option(
    "--ttd-start-date",
    required=True,
    type=click.DateTime(),
    help="Start date of the period to request (format: YYYY-MM-DD)",
)
@click.option(
    "--ttd-end-date",
    required=True,
    type=click.DateTime(),
    help="End date of the period to request (format: YYYY-MM-DD)",
)
@processor("ttd_login", "ttd_password")
def the_trade_desk(**kwargs):
    return TheTradeDeskReader(**extract_args("ttd_", kwargs))


class TheTradeDeskReader(Reader):
    def __init__(
        self,
        login,
        password,
        advertiser_id,
        report_template_name,
        report_schedule_name,
        start_date,
        end_date,
    ):
        self.headers = build_headers(login, password)
        self.advertiser_ids = list(advertiser_id)
        self.report_template_name = report_template_name
        self.report_schedule_name = report_schedule_name
        self.start_date = start_date
        # Report end date is exclusive: to become inclusive, it should be incremented by 1 day
        self.end_date = end_date + timedelta(days=1)

        self.validate_dates()

    def validate_dates(self):
        if self.end_date - timedelta(days=1) < self.start_date:
            raise ClickException(
                "Report end date should be equal or ulterior to report start date."
            )

    def make_api_call(self, method, endpoint, payload={}):
        url = f"{API_HOST}/{endpoint}"
        response = requests.request(
            method=method, url=url, headers=self.headers, json=payload
        )
        if response.ok:
            if response.content:
                print(response.json())
                return response.json()
        else:
            response.raise_for_status()

    def get_report_template_id(self):
        logging.info(f"Collecting ReportTemplateId of '{self.report_template_name}'")
        method, endpoint = API_ENDPOINTS["get_report_template_id"]
        payload = {"NameContains": self.report_template_name, **DEFAULT_PAGING_ARGS}
        json_response = self.make_api_call(method, endpoint, payload)
        if json_response["ResultCount"] == 0:
            raise Exception(
                f"No existing ReportTemplate match '{self.report_template_name}'"
            )
        if json_response["ResultCount"] > 1:
            raise Exception(
                f"""'{self.report_template_name}' match more than one ReportTemplate.
                Please specify the exact name of the ReportTemplate you wish to retrieve."""
            )
        else:
            report_template_id = json_response["Result"][0]["ReportTemplateId"]
            logging.info(f"Retrieved ReportTemplateId: {report_template_id}")
            return report_template_id

    def create_report_schedule(self, report_template_id):
        method, endpoint = API_ENDPOINTS["create_report_schedule"]
        payload = {
            "ReportScheduleName": self.report_schedule_name,
            "ReportTemplateId": report_template_id,
            "AdvertiserFilters": self.advertiser_ids,
            "ReportStartDateInclusive": self.start_date.isoformat(),
            "ReportEndDateExclusive": self.end_date.isoformat(),
            **DEFAULT_REPORT_SCHEDULE_ARGS,
        }
        logging.info(f"Creating ReportSchedule: {payload}")
        json_response = self.make_api_call(method, endpoint, payload)
        report_schedule_id = json_response["ReportScheduleId"]
        return report_schedule_id

    @retry(
        wait=wait_exponential(multiplier=1, min=60, max=3600),
        stop=stop_after_delay(36000),
    )
    def _wait_for_download_url(self, report_schedule_id):
        report_execution_details = self.get_report_execution_details(report_schedule_id)
        if report_execution_details["ReportExecutionState"] == "Pending":
            raise Exception(f"ReportSchedule '{report_schedule_id}' is still running.")
        else:
            # As the ReportSchedule that we just created runs only once,
            # the API response will include only one ReportDelivery (so we can get index "[0]")
            download_url = report_execution_details["ReportDeliveries"][0][
                "DownloadURL"
            ]
            logging.info(
                f"ReportScheduleId '{report_schedule_id}' is ready. DownloadURL: {download_url}"
            )
            return download_url

    def get_report_execution_details(self, report_schedule_id):
        method, endpoint = API_ENDPOINTS["get_report_execution_details"]
        payload = {
            "AdvertiserIds": self.advertiser_ids,
            "ReportScheduleIds": [report_schedule_id],
            **DEFAULT_PAGING_ARGS,
        }
        json_response = self.make_api_call(method, endpoint, payload)
        # As the ReportScheduleId that we provided as a payload is globally unique,
        # the API response will include only one Result (so we can get index "[0]")
        report_execution_details = json_response["Result"][0]
        return report_execution_details

    def download_report(self, download_url):
        report = requests.get(url=download_url, headers=self.headers, stream=True)
        return get_report_generator_from_flat_file(report.iter_lines())

    def delete_report_schedule(self, report_schedule_id):
        logging.info(f"Deleting ReportScheduleId '{report_schedule_id}'")
        method, endpoint = API_ENDPOINTS["delete_report_schedule"]
        self.make_api_call(method, f"{endpoint}/{report_schedule_id}")

    def read(self):
        report_template_id = self.get_report_template_id()
        report_schedule_id = self.create_report_schedule(report_template_id)
        download_url = self._wait_for_download_url(report_schedule_id)
        data = self.download_report(download_url)

        def result_generator():
            for record in data:
                yield {
                    k: format_date(v) if k == "Date" else v for k, v in record.items()
                }

        yield NormalizedJSONStream(
            "results_" + "_".join(self.advertiser_ids), result_generator()
        )

        self.delete_report_schedule(report_schedule_id)
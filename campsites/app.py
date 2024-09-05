import logging
import os
import json
from collections import defaultdict
from datetime import date, datetime
from typing import Callable, List, Dict, Any

from campsite import filter_to_criteria, get_table_data
from messaging import send_message
from recreation_gov import (
    get_campground_id,
    rg_get_all_available_campsites,
    rg_get_campground_url,
)
from reserve_california import (
    get_facility_ids,
    rc_get_all_available_campsites,
    rc_get_campground_url,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def create_table_string(data: List[Dict[str, str]]) -> str:
    header = list(data[0].keys())
    values = [list(x.values()) for x in data]
    output = [header] + values
    tab_length = 4
    lengths = [max(len(str(x)) for x in line) + tab_length for line in zip(*output)]
    row_formatter = "".join(["{:" + str(x) + "s}" for x in lengths])
    table_string = "\n".join([row_formatter.format(*row) for row in output])
    return table_string

def create_log(
    table_data: List[Dict[str, str]],
    campground_id: str,
    get_campground_url: Callable[[str], str],
) -> str:
    return (
        f"Found Availability:\n\n{create_table_string(table_data)}\n"
        + f"Reserve a spot here: {get_campground_url(campground_id)}"
    )

def log_and_text_error_message(
    message: str, error: str, check_every: int, notified_errors: defaultdict[str, int]
) -> None:
    current_date = str(datetime.now().date())
    error_message = (
        f"{message} Trying again in {check_every} minutes.\n"
        f"Error: {error}\n"
        f"Date: {current_date}"
    )
    logger.error(error_message)
    if error_message not in notified_errors:
        try:
            notified_errors[error_message] += 1
            if notified_errors[error_message] >= 3:
                send_message(error_message)
        except Exception:
            pass

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    # Parse the request data from API Gateway
    data = event.get('body')
    
    if isinstance(data, str):
        data = json.loads(data)
    
    phone_number = data.get('phone_number')
    campgrounds = data.get('campground', [])
    nights = data.get('nights', 1)
    day = data.get('day', [])
    require_same_site = data.get('require_same_site', False)
    months = data.get('months', 1)
    api = data.get('api', 'reservecalifornia')
    check_every = data.get('check_every', 5)
    ignore = data.get('ignore', [])
    notify = data.get('notify', False)
    calendar_date = data.get('calendar_date', [])
    sub_campground = data.get('sub_campground', [])

    if phone_number:
        os.environ["TWILIO_TO_NUMBER"] = phone_number

    if nights < 1:
        return {
            'statusCode': 400,
            'body': json.dumps({'message': 'Nights must be greater than 1.'})
        }

    notified: defaultdict[str, set] = defaultdict(set)
    notified_errors: defaultdict[str, int] = defaultdict(lambda: 0)

    start_date = datetime.today()
    dates = [datetime.strptime(x, "%m/%d/%Y") for x in calendar_date] if calendar_date else []

    results = []

    for campground in campgrounds:
        if api == "reservecalifornia":
            if not campground.isdigit():
                logger.info(
                    "ReserveCalifornia must use facility ID. Searching for facility "
                    + "IDs using provided `campground_id` (note: this must be the "
                    + "park that the campground is in)"
                )
                facility_id_table = create_table_string(
                    get_facility_ids(campground)
                )
                logger.info(f"Found facilities in park:\n\n{facility_id_table}\n")
                return {
                    'statusCode': 200,
                    'body': json.dumps({'facility_ids': facility_id_table})
                }

            get_campground_url = rc_get_campground_url
            get_all_available_campsites = rc_get_all_available_campsites
        else:
            get_campground_url = rg_get_campground_url
            get_all_available_campsites = rg_get_all_available_campsites
        
        try:
            campground_id = (
                campground
                if api == "reservecalifornia"
                else get_campground_id(campground)
            )
            available = get_all_available_campsites(
                campground_id=campground_id, start_date=start_date, months=months
            )
        except Exception as e:
            log_and_text_error_message(
                message="Failed to retrieve availability.",
                error=str(e),
                check_every=check_every,
                notified_errors=notified_errors,
            )
            continue
        
        available = filter_to_criteria(
            available,
            weekdays=day,
            nights=nights,
            ignore=ignore,
            require_same_site=require_same_site,
            calendar_dates=dates,
            sub_campgrounds=sub_campground,
        )
        
        if available:
            table_data = get_table_data(available)
            log_message = create_log(table_data, campground_id, get_campground_url)
            logger.info(log_message)
            
            if notify and start_date.date() not in notified[campground]:
                text_message = create_log(
                    table_data[0:2], campground_id, get_campground_url
                )
                try:
                    send_message(text_message)
                except Exception as e:
                    log_and_text_error_message(
                        message="Failed to retrieve availability.",
                        error=str(e),
                        check_every=check_every,
                        notified_errors=notified_errors,
                    )
                    continue
                notified[campground].add(start_date.date())
            results.append({'campground': campground, 'availability': table_data})
        else:
            logger.info(
                f"No availability found for {campground} :( "
                f"Trying again in {check_every} minutes."
            )

    return {
        'statusCode': 200,
        'body': json.dumps({'results': results}, indent=4)
    }

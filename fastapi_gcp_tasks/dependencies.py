# Standard Library Imports
from datetime import datetime
from typing import Any, Callable

# Third Party Imports
from fastapi import Depends, Header, HTTPException


def max_retries(count: int = 20) -> Callable[[Any], bool]:
    """Raises an http exception (with status 200) after max retries are exhausted."""

    def retries_dep(meta: CloudTasksHeaders = Depends()) -> bool:
        # count starts from 0 so equality check is required
        if meta.retry_count >= count:
            raise HTTPException(status_code=200, detail="Max retries exhausted")
        return True

    return retries_dep


class CloudTasksHeaders:
    """
    Extracts known headers sent by Cloud Tasks.

    Full list: https://cloud.google.com/tasks/docs/creating-http-target-tasks#handler
    """

    def __init__(
        self,
        x_cloudtasks_taskretrycount: int = Header(0),
        x_cloudtasks_taskexecutioncount: int = Header(0),
        x_cloudtasks_queuename: str = Header(""),
        x_cloudtasks_taskname: str = Header(""),
        x_cloudtasks_tasketa: float = Header(0),
        x_cloudtasks_taskpreviousresponse: int = Header(0),
        x_cloudtasks_taskretryreason: str = Header(""),
    ) -> None:
        self.retry_count = x_cloudtasks_taskretrycount
        self.execution_count = x_cloudtasks_taskexecutioncount
        self.queue_name = x_cloudtasks_queuename
        self.task_name = x_cloudtasks_taskname
        self.eta = datetime.fromtimestamp(x_cloudtasks_tasketa)
        self.previous_response = x_cloudtasks_taskpreviousresponse
        self.retry_reason = x_cloudtasks_taskretryreason

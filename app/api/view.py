"""How a job is shown on the work screen, kept beside the job: the ratio the
player's Ratio button was left on (view.json, next to subtitle_style.json).

In the job's work folder rather than next to its result, so the choice can be
written the moment a dub starts -- a draft's ratio is handed to the job it
becomes -- and not only once there is a finished video.
"""
import os

from fastapi import APIRouter, HTTPException

from app import ratio, state
from app.api._shared import ratio_errors_as_http, work_dir_of
from app.i18n import t

router = APIRouter()


def _work(jid: str) -> str:
    job = state.job_store.get(jid)
    if job is None:
        raise HTTPException(status_code=404, detail=t("Unknown job: {jid}", jid=jid))
    work = work_dir_of(job)
    if not work or not os.path.isdir(work):
        raise HTTPException(status_code=404, detail=t("This project's folder is no longer on disk."))
    return work


@router.get("/api/dub/jobs/{jid}/view")
def view_get(jid: str):
    return ratio.load_view(_work(jid))


@router.put("/api/dub/jobs/{jid}/view")
def view_put(jid: str, body: dict):
    work = _work(jid)
    with ratio_errors_as_http():
        return ratio.save_view(work, body)

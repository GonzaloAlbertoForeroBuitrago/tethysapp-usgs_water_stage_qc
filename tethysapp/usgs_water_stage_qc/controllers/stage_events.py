from __future__ import annotations

from tethys_sdk.routing import controller

from ..app import App


@controller(
    name="stage_events",
    url="stage-events/{state}/{gage_id}/",
)
def stage_events(request, state, gage_id):
    context = {
        "state": state.upper(),
        "gage_id": gage_id,
    }

    return App.render(
        request,
        "stage_events.html",
        context,
    )

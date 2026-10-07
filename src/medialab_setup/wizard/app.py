"""The wizard's FastAPI app: four pages over the CLI's phases, loopback only, token-guarded."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from medialab_setup.bindings import ASKED_FIELDS, BINDINGS, REQUIRED_FIELDS
from medialab_setup.checks import CredentialChecker
from medialab_setup.envfile import EnvTemplate
from medialab_setup.generate import collect_existing
from medialab_setup.guides import GUIDES, Guide, guide_for
from medialab_setup.host import HostPhase, HostRow
from medialab_setup.jellyfin_client import JellyfinClient
from medialab_setup.preflight import PREREQUISITES, Preflight, Row
from medialab_setup.shell import Shell
from medialab_setup.wizard.log import LineLog
from medialab_setup.wizard.prompter import WebPrompter, extra_field_name
from medialab_setup.wizard.runner import Run, RunState, start_run
from medialab_setup.workspace import Workspace

TOKEN_COOKIE = "medialab_setup_token"
TOKEN_QUERY = "t"
TOKEN_BYTES = 32
TEMPLATES_DIR = Path(__file__).parent / "templates"
IDLE_TIMEOUT_SECONDS = 600
HOST_SETUP_DOC = "docs/host-setup.md"
WEB_UI_URL = "http://127.0.0.1:8081"
STATE_SET = "set"
STATE_ACCEPTED = "accepted"
STATE_REJECTED = "rejected"
STATE_UNVERIFIED = "unverified"
STATE_EMPTY = "empty"


@dataclass
class WizardState:
    workspace: Workspace
    shell: Shell
    checker: CredentialChecker
    token: str = field(default_factory=lambda: secrets.token_urlsafe(TOKEN_BYTES))
    make_jellyfin_client: type[JellyfinClient] = JellyfinClient
    run: Run | None = None
    last_activity: float = field(default_factory=time.monotonic)
    done: bool = False

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def idle_for(self, now: float | None = None) -> float:
        return (time.monotonic() if now is None else now) - self.last_activity


def should_stop(state: WizardState, now: float | None = None) -> bool:
    """Exit once the operator is done, or after the idle window with no run in progress."""
    if state.done:
        return True
    running = state.run is not None and not state.run.finished
    return not running and state.idle_for(now) >= IDLE_TIMEOUT_SECONDS


@dataclass(frozen=True)
class FieldView:
    field: str
    guide: Guide
    required: bool
    current_state: str
    current_value: str


@dataclass(frozen=True)
class ExtraView:
    name: str
    target: str
    key: str
    default: str
    help_text: str


def field_views(workspace: Workspace) -> list[FieldView]:
    existing = collect_existing(workspace, BINDINGS)
    views: list[FieldView] = []
    for name in ASKED_FIELDS:
        guide = guide_for(name)
        value = existing.plain_value(name) or ""
        if not value:
            state, shown = STATE_EMPTY, ""
        elif guide.secret:
            state, shown = STATE_SET, ""
        else:
            state, shown = STATE_SET, value
        views.append(FieldView(name, guide, name in REQUIRED_FIELDS, state, shown))
    return views


def extra_views(workspace: Workspace) -> list[ExtraView]:
    bound = {(binding.target, binding.key) for binding in BINDINGS}
    views: list[ExtraView] = []
    for target in workspace.env_targets():
        if not target.example_path.exists():
            continue
        template = EnvTemplate.from_path(target.example_path)
        for entry in template.entries:
            if (target.name, entry.key) in bound:
                continue
            views.append(
                ExtraView(
                    extra_field_name(target.name, entry.key),
                    target.name,
                    entry.key,
                    entry.default,
                    " ".join(c.lstrip("# ") for c in entry.comments),
                )
            )
    return views


def missing_required(form: dict[str, str], workspace: Workspace) -> list[str]:
    existing = collect_existing(workspace, BINDINGS)
    return [
        guide_for(name).title
        for name in REQUIRED_FIELDS
        if not form.get(name, "").strip() and not (existing.plain_value(name) or "")
    ]


def create_app(state: WizardState) -> FastAPI:
    app = FastAPI(title="medialab setup", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    def require_token(request: Request) -> None:
        if request.cookies.get(TOKEN_COOKIE) != state.token:
            raise HTTPException(HTTPStatus.FORBIDDEN, "missing or wrong wizard token")
        state.touch()

    def render(request: Request, template: str, **context: object) -> HTMLResponse:
        return templates.TemplateResponse(
            request, template, {"request": request, "token": state.token, **context}
        )

    @app.get("/", response_class=HTMLResponse, response_model=None)
    def enter(request: Request) -> Response:
        if request.query_params.get(TOKEN_QUERY) != state.token:
            raise HTTPException(HTTPStatus.FORBIDDEN, "open the URL printed by medialab-setup")
        response = RedirectResponse("/prereqs", status_code=HTTPStatus.SEE_OTHER)
        response.set_cookie(TOKEN_COOKIE, state.token, httponly=True, samesite="strict")
        state.touch()
        return response

    @app.get(
        "/prereqs",
        response_class=HTMLResponse,
        response_model=None,
        dependencies=[Depends(require_token)],
    )
    def prereqs(request: Request) -> HTMLResponse:
        result = Preflight(
            state.workspace, state.shell, WebPrompter({}, _scratch_log()), interactive=False
        ).run()
        return render(
            request,
            "prereqs.html",
            rows=result.rows,
            failed=result.failed,
            installable={p.name for p in PREREQUISITES},
        )

    @app.post(
        "/prereqs/install/{name}",
        response_class=HTMLResponse,
        response_model=None,
        dependencies=[Depends(require_token)],
    )
    def install(request: Request, name: str) -> HTMLResponse:
        preflight = Preflight(
            state.workspace, state.shell, WebPrompter({}, _scratch_log()), assume_yes=True
        )
        row = preflight.install(name)
        return render(request, "partials/row.html", row=row)

    @app.get(
        "/credentials",
        response_class=HTMLResponse,
        response_model=None,
        dependencies=[Depends(require_token)],
    )
    def credentials(request: Request) -> HTMLResponse:
        return render(
            request,
            "credentials.html",
            fields=field_views(state.workspace),
            extras=extra_views(state.workspace),
            errors=[],
        )

    @app.post(
        "/check/{name}",
        response_class=HTMLResponse,
        response_model=None,
        dependencies=[Depends(require_token)],
    )
    def check(request: Request, name: str, value: str = Form("")) -> HTMLResponse:
        try:
            guide = guide_for(name)
        except KeyError as error:
            raise HTTPException(HTTPStatus.NOT_FOUND, name) from error
        if not value.strip():
            outcome, detail = STATE_EMPTY, ""
        elif guide.check is None:
            outcome, detail = STATE_SET, ""
        else:
            result = state.checker.run(guide.check, value.strip())
            if result.unverified:
                outcome = STATE_UNVERIFIED
            elif result.ok:
                outcome = STATE_ACCEPTED
            else:
                outcome = STATE_REJECTED
            detail = result.detail
        return render(request, "partials/check.html", name=name, outcome=outcome, detail=detail)

    @app.post(
        "/credentials",
        response_class=HTMLResponse,
        response_model=None,
        dependencies=[Depends(require_token)],
    )
    async def submit(request: Request) -> Response:
        form = {k: str(v) for k, v in (await request.form()).items()}
        missing = missing_required(form, state.workspace)
        rejected = [
            guide_for(name).title
            for name in ASKED_FIELDS
            if form.get(name, "").strip()
            and guide_for(name).check is not None
            and _rejected(state.checker, name, form[name].strip())
        ]
        errors = [f"{title} is required" for title in missing] + [
            f"{title} was rejected by the service" for title in rejected
        ]
        if errors:
            return render(
                request,
                "credentials.html",
                fields=field_views(state.workspace),
                extras=extra_views(state.workspace),
                errors=errors,
            )
        if state.run is None or state.run.finished:
            state.run = start_run(
                state.workspace,
                state.shell,
                state.checker,
                form,
                make_jellyfin_client=state.make_jellyfin_client,
            )
        return RedirectResponse("/run", status_code=HTTPStatus.SEE_OTHER)

    @app.get(
        "/run",
        response_class=HTMLResponse,
        response_model=None,
        dependencies=[Depends(require_token)],
    )
    def run_page(request: Request) -> Response:
        if state.run is None:
            return RedirectResponse("/credentials", status_code=HTTPStatus.SEE_OTHER)
        return render(request, "run.html", run=state.run)

    @app.get(
        "/events",
        response_class=HTMLResponse,
        response_model=None,
        dependencies=[Depends(require_token)],
    )
    def events(request: Request, after: int = 0) -> HTMLResponse:
        if state.run is None:
            raise HTTPException(HTTPStatus.NOT_FOUND, "no run")
        lines, index = state.run.log.since(after)
        return render(
            request,
            "partials/events.html",
            lines=lines,
            index=index,
            run=state.run,
            finished=state.run.finished,
        )

    @app.get(
        "/result",
        response_class=HTMLResponse,
        response_model=None,
        dependencies=[Depends(require_token)],
    )
    def result(request: Request) -> Response:
        if state.run is None or not state.run.finished:
            return RedirectResponse("/run", status_code=HTTPStatus.SEE_OTHER)
        return render(
            request,
            "result.html",
            run=state.run,
            succeeded=state.run.state is RunState.SUCCEEDED,
            web_ui_url=WEB_UI_URL,
            host_setup_doc=HOST_SETUP_DOC,
            host_rows=_host_status(state),
        )

    @app.post(
        "/host/apply",
        response_class=HTMLResponse,
        response_model=None,
        dependencies=[Depends(require_token)],
    )
    def host_apply(request: Request) -> HTMLResponse:
        """Apply every automatable host step (one UAC prompt); manual ones stay listed."""
        HostPhase(
            state.workspace,
            state.shell,
            WebPrompter({}, _scratch_log()),
            assume_yes=True,
            interactive=True,
        ).run()
        return render(request, "partials/host_rows.html", host_rows=_host_status(state))

    @app.post(
        "/done",
        response_class=HTMLResponse,
        response_model=None,
        dependencies=[Depends(require_token)],
    )
    def done(request: Request) -> HTMLResponse:
        state.done = True
        return render(request, "done.html")

    return app


def _host_status(state: WizardState) -> list[HostRow]:
    return HostPhase(
        state.workspace, state.shell, WebPrompter({}, _scratch_log()), interactive=False
    ).status()


def _rejected(checker: CredentialChecker, name: str, value: str) -> bool:
    guide = guide_for(name)
    assert guide.check is not None
    result = checker.run(guide.check, value)
    return not result.ok and not result.unverified


def _scratch_log() -> LineLog:
    return LineLog()


__all__ = ["GUIDES", "Row", "WizardState", "create_app", "should_stop"]

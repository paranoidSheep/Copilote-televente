"""Injection de dépendances : les routes reçoivent l'`Application` stockée dans l'état de FastAPI."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from copilote.application import Application


def obtenir_application(request: Request) -> Application:
    return cast(Application, request.app.state.application)


ApplicationDep = Annotated[Application, Depends(obtenir_application)]

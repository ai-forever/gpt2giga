import json
from functools import wraps

import gigachat
from fastapi import HTTPException


def exceptions_handler(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except gigachat.exceptions.ResponseError as e:
            if len(e.args) == 4:
                url, status_code, message, _ = e.args
                try:
                    error_detail = json.loads(message)
                except Exception:
                    error_detail = message
                raise HTTPException(
                    status_code=status_code,
                    detail={
                        "url": str(url),
                        "error": error_detail,
                    },
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "Unexpected ResponseError structure",
                        "args": e.args,
                    },
                )

    return wrapper

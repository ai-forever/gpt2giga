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
            url, status_code, message, _ = e.args
            error_detail = json.loads(message)
            raise HTTPException(
                status_code=status_code,
                detail={
                    "url": str(url),
                    "error": error_detail,
                },
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return wrapper
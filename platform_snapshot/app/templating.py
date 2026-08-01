from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import get_settings

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["settings"] = get_settings()
templates.env.globals["app_name"] = "Brother Bot"


def fmt_money(value, currency: str = "$") -> str:
    try:
        return f"{currency}{value:,.2f}"
    except (TypeError, ValueError):
        return "—"


templates.env.filters["money"] = fmt_money

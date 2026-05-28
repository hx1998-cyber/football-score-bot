from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile


def generate_worldcup_match_poster(
    home_team: str,
    away_team: str,
    kickoff_time: str,
    odds: str,
) -> str | None:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    image = Image.new("RGB", (900, 500), "#0b3d2e")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 900, 90), fill="#d4af37")
    draw.text((40, 30), "World Cup Match", fill="#101010")
    draw.text((80, 170), f"{home_team} vs {away_team}", fill="#ffffff")
    draw.text((80, 245), f"Kickoff: {kickoff_time}", fill="#ffffff")
    draw.text((80, 310), f"Odds: {odds}", fill="#ffffff")
    temp = NamedTemporaryFile(delete=False, suffix=".png")
    temp.close()
    image.save(temp.name)
    return str(Path(temp.name))


def generate_team_card(team_name: str, subtitle: str = "") -> str | None:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    image = Image.new("RGB", (640, 360), "#152238")
    draw = ImageDraw.Draw(image)
    draw.text((40, 120), team_name, fill="#ffffff")
    if subtitle:
        draw.text((40, 190), subtitle, fill="#d4af37")
    temp = NamedTemporaryFile(delete=False, suffix=".png")
    temp.close()
    image.save(temp.name)
    return str(Path(temp.name))

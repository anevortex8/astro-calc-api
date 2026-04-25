from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class BirthData(BaseModel):
    birth_date: str
    birth_time: str
    birth_city: str
    birth_state: str = ""
    birth_country: str = ""
    birth_time_unknown: bool = False

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/calculate-chart")
def calculate_chart(data: BirthData):
    return {
        "resolved_location": {
            "city": data.birth_city,
            "country": data.birth_country,
            "timezone": "America/Sao_Paulo"
        },
        "chart_json": {
            "is_mock": True,
            "natal_chart": {
                "sun": {"sign": "Leo", "degree": 22, "house": 10},
                "moon": {"sign": "Cancer", "degree": 5, "house": 7},
                "ascendant": {"sign": "Capricorn", "degree": 13}
            },
            "houses": [],
            "natal_aspects": [],
            "current_transits": [],
            "ancorada_extraction": {
                "central_anchor": {
                    "pattern": "Vênus Negociada",
                    "reason": "Mock para testes"
                }
            }
        }
    }

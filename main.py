"""
FastAPI - Calculate Chart endpoint para sistema ANCORADA
=========================================================
Endpoint POST /calculate-chart retorna chart_json mock consistente
e astrologicamente coerente para alimentar diagnósticos profundos.

Para rodar:
    uvicorn main:app --reload --port 8000
"""

from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="ANCORADA Chart API",
    description="API de cálculo astrológico para sistema de diagnóstico ANCORADA",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Schemas de entrada
# =============================================================================
class BirthData(BaseModel):
    birth_date: str = Field(..., description="Data de nascimento YYYY-MM-DD")
    birth_time: Optional[str] = Field(None, description="Hora de nascimento HH:MM")
    birth_city: str
    birth_state: Optional[str] = None
    birth_country: str
    birth_time_unknown: bool = False


# =============================================================================
# Helpers astrológicos
# =============================================================================
SIGNS = [
    "Áries", "Touro", "Gêmeos", "Câncer", "Leão", "Virgem",
    "Libra", "Escorpião", "Sagitário", "Capricórnio", "Aquário", "Peixes",
]

SIGN_ELEMENTS = {
    "Áries": "fogo", "Leão": "fogo", "Sagitário": "fogo",
    "Touro": "terra", "Virgem": "terra", "Capricórnio": "terra",
    "Gêmeos": "ar", "Libra": "ar", "Aquário": "ar",
    "Câncer": "água", "Escorpião": "água", "Peixes": "água",
}

SIGN_MODALITIES = {
    "Áries": "cardinal", "Câncer": "cardinal", "Libra": "cardinal", "Capricórnio": "cardinal",
    "Touro": "fixo", "Leão": "fixo", "Escorpião": "fixo", "Aquário": "fixo",
    "Gêmeos": "mutável", "Virgem": "mutável", "Sagitário": "mutável", "Peixes": "mutável",
}

PLANET_RULERS = {
    "Áries": "Marte", "Touro": "Vênus", "Gêmeos": "Mercúrio", "Câncer": "Lua",
    "Leão": "Sol", "Virgem": "Mercúrio", "Libra": "Vênus", "Escorpião": "Plutão",
    "Sagitário": "Júpiter", "Capricórnio": "Saturno", "Aquário": "Urano", "Peixes": "Netuno",
}


def longitude_to_sign(longitude: float) -> dict:
    """Converte longitude eclíptica (0-360°) em signo + grau dentro do signo."""
    longitude = longitude % 360
    sign_index = int(longitude // 30)
    degree_in_sign = longitude % 30
    deg = int(degree_in_sign)
    minutes = int((degree_in_sign - deg) * 60)
    sign = SIGNS[sign_index]
    return {
        "sign": sign,
        "degree": round(degree_in_sign, 4),
        "degree_formatted": f"{deg}°{minutes:02d}'",
        "absolute_longitude": round(longitude, 4),
        "element": SIGN_ELEMENTS[sign],
        "modality": SIGN_MODALITIES[sign],
        "ruler": PLANET_RULERS[sign],
    }


def calc_aspect(lon1: float, lon2: float) -> Optional[dict]:
    """Calcula aspecto entre duas longitudes eclípticas."""
    diff = abs(lon1 - lon2) % 360
    if diff > 180:
        diff = 360 - diff

    aspects = [
        ("conjunção", 0, 8),
        ("oposição", 180, 8),
        ("trígono", 120, 7),
        ("quadratura", 90, 7),
        ("sextil", 60, 5),
        ("quincúncio", 150, 3),
        ("semi-sextil", 30, 2),
    ]
    for name, angle, max_orb in aspects:
        orb = abs(diff - angle)
        if orb <= max_orb:
            return {
                "aspect": name,
                "exact_angle": angle,
                "orb": round(orb, 2),
                "applying": lon1 < lon2,
                "strength": "forte" if orb <= max_orb / 2 else "moderado",
            }
    return None


# =============================================================================
# Mock astrológico consistente
# =============================================================================
# Carta arquetípica desenhada para acionar TODOS os pilares ANCORADA:
# - Sol em Câncer (4) - core emocional/familiar
# - Lua em Capricórnio (10) - tensão emocional/profissional, oposição ao Sol
# - Ascendente em Libra - busca de harmonia, evita conflito
# - Saturno em Áries quadratura Sol/Lua - SATURNO DESORIENTADO clássico
# - Vênus em Gêmeos casa 9 - VÊNUS NEGOCIADA (dispersa, intelectualizada)
# - Marte em Peixes casa 6 - MARTE APAGADO (em queda, dissolvido em rotina)
# - Quíron em Áries conjunto Saturno - QUÍRON NÃO INTEGRADO (ferida de identidade)
# - Plutão em Escorpião casa 2 - âncora central de transformação/poder
# Longitudes em graus eclípticos absolutos (0° = 0° Áries).

NATAL_LONGITUDES = {
    "sun":        102.45,   # 12°27' Câncer
    "moon":       284.18,   # 14°11' Capricórnio (oposto ao Sol)
    "ascendant":  187.33,   # 7°20' Libra
    "mercury":     95.72,   # 5°43' Câncer
    "venus":       72.10,   # 12°06' Gêmeos
    "mars":       348.55,   # 18°33' Peixes
    "jupiter":    215.40,   # 5°24' Escorpião
    "saturn":      18.92,   # 18°55' Áries (quadratura ao Sol/Lua)
    "uranus":     268.15,   # 28°09' Sagitário
    "neptune":    295.62,   # 25°37' Capricórnio
    "pluto":      221.83,   # 11°50' Escorpião (na casa 2)
    "chiron":      12.40,   # 12°24' Áries (conjunto Saturno)
    "lilith":     156.27,   # 6°16' Virgem
    "fortune":    169.55,   # 19°33' Virgem
    "midheaven":   97.10,   # 7°06' Câncer
}


def build_planet(longitude: float, retrograde: bool = False, speed: float = 1.0,
                 house: int = 1, declination: float = 0.0) -> dict:
    """Monta dicionário completo de um planeta a partir de sua longitude."""
    sign_data = longitude_to_sign(longitude)
    return {
        **sign_data,
        "house": house,
        "retrograde": retrograde,
        "speed": speed,
        "declination": declination,
    }


def build_natal_chart() -> dict:
    """Monta natal_chart com todos os planetas + pontos sensíveis."""
    # Casas (atribuídas para refletir a história ANCORADA)
    houses_map = {
        "sun": 10,        # Sol na casa 10 - vocação visível
        "moon": 4,        # Lua na casa 4 - raiz emocional (mas oposição inverte)
        "ascendant": 1,
        "mercury": 9,     # Mercúrio em Câncer casa 9 - fala que oscila entre familiar e expansivo
        "venus": 9,       # Vênus em Gêmeos casa 9 - DISPERSÃO afetiva
        "mars": 6,        # Marte em Peixes casa 6 - rotina dissolve a ação
        "jupiter": 2,     # Júpiter em Escorpião casa 2 - recursos profundos
        "saturn": 7,      # Saturno em Áries casa 7 - estrutura via outros
        "uranus": 3,      # Urano em Sagitário casa 3
        "neptune": 4,     # Netuno em Capricórnio casa 4 - dissolução nas raízes
        "pluto": 2,       # Plutão em Escorpião casa 2 - poder via recursos
        "chiron": 7,      # Quíron em Áries casa 7 - ferida de identidade nos vínculos
        "lilith": 12,     # Lilith em Virgem casa 12 - sombra do trabalho oculto
        "fortune": 12,
        "midheaven": 10,
    }
    retrogrades = {"saturn", "neptune", "pluto", "chiron"}
    speeds = {
        "sun": 0.9856, "moon": 13.176, "mercury": 1.382, "venus": 1.103, "mars": 0.524,
        "jupiter": 0.083, "saturn": -0.034, "uranus": 0.039, "neptune": -0.005,
        "pluto": -0.003, "chiron": -0.011, "lilith": 0.111, "fortune": 0.0, "ascendant": 0.0,
        "midheaven": 0.0,
    }

    chart = {}
    for planet, lon in NATAL_LONGITUDES.items():
        chart[planet] = build_planet(
            longitude=lon,
            retrograde=planet in retrogrades,
            speed=speeds.get(planet, 1.0),
            house=houses_map.get(planet, 1),
            declination=round(((lon % 360) - 180) * 0.13, 2),
        )
    return chart


def build_houses(asc_longitude: float) -> list:
    """Monta as 12 casas usando sistema Placidus simplificado (cúspides equidistantes a partir do AC)."""
    house_themes = [
        "Identidade e expressão pessoal",
        "Recursos, valores e segurança material",
        "Comunicação, irmãos e ambiente próximo",
        "Lar, raízes e mundo emocional",
        "Criatividade, prazer e filhos",
        "Trabalho, rotina e saúde",
        "Relacionamentos e parcerias",
        "Transformação, sexualidade e recursos compartilhados",
        "Filosofia, viagens e expansão",
        "Carreira, vocação e imagem pública",
        "Amizades, grupos e visão de futuro",
        "Inconsciente, espiritualidade e dissolução",
    ]
    houses = []
    for i in range(12):
        cusp_lon = (asc_longitude + i * 30) % 360
        sign_data = longitude_to_sign(cusp_lon)
        houses.append({
            "number": i + 1,
            "cusp_longitude": round(cusp_lon, 4),
            "cusp_sign": sign_data["sign"],
            "cusp_degree": sign_data["degree"],
            "cusp_formatted": f"{sign_data['degree_formatted']} {sign_data['sign']}",
            "ruler": sign_data["ruler"],
            "theme": house_themes[i],
        })
    return houses


def build_natal_aspects() -> list:
    """Calcula aspectos entre todos os planetas natais."""
    aspect_planets = [
        "sun", "moon", "mercury", "venus", "mars",
        "jupiter", "saturn", "uranus", "neptune", "pluto", "chiron",
    ]
    aspects = []
    for i, p1 in enumerate(aspect_planets):
        for p2 in aspect_planets[i + 1:]:
            aspect = calc_aspect(NATAL_LONGITUDES[p1], NATAL_LONGITUDES[p2])
            if aspect:
                aspects.append({
                    "planet1": p1,
                    "planet2": p2,
                    **aspect,
                })
    return aspects


def build_current_transits() -> list:
    """Trânsitos atuais (mock baseado em posições aproximadas para abril/2026)."""
    # Posições eclípticas aproximadas de planetas lentos em meados de 2026
    transit_longitudes = {
        "saturn":  357.20,   # 27°12' Peixes - aproximando-se do Marte natal
        "jupiter": 105.40,   # 15°24' Câncer - conjunção ao Sol natal
        "uranus":   65.85,   # 5°51' Gêmeos - quadratura à Lua natal
        "neptune":   2.30,   # 2°18' Áries - conjunção ao Quíron/Saturno natal
        "pluto":   303.45,   # 3°27' Aquário - quadratura ao Júpiter natal
    }
    transits = []
    natal_targets = ["sun", "moon", "venus", "mars", "saturn", "chiron"]
    for tplanet, tlon in transit_longitudes.items():
        sign_data = longitude_to_sign(tlon)
        for target in natal_targets:
            aspect = calc_aspect(tlon, NATAL_LONGITUDES[target])
            if aspect and aspect["orb"] <= 3.0:
                transits.append({
                    "transit_planet": tplanet,
                    "transit_position": {
                        "sign": sign_data["sign"],
                        "degree_formatted": sign_data["degree_formatted"],
                        "longitude": round(tlon, 4),
                    },
                    "natal_target": target,
                    "aspect": aspect["aspect"],
                    "orb": aspect["orb"],
                    "applying": aspect["applying"],
                    "strength": aspect["strength"],
                    "active_until": "2026-08-15",
                })
    return transits


def build_ancorada_extraction(natal_chart: dict, aspects: list) -> dict:
    """
    Extrai os 4 pilares ANCORADA + âncora central a partir da carta.
    Esta é a camada que alimenta o diagnóstico profundo.
    """
    saturn = natal_chart["saturn"]
    venus = natal_chart["venus"]
    mars = natal_chart["mars"]
    chiron = natal_chart["chiron"]
    pluto = natal_chart["pluto"]

    # Detectar aspectos tensos envolvendo Saturno
    saturn_hard_aspects = [
        a for a in aspects
        if (a["planet1"] == "saturn" or a["planet2"] == "saturn")
        and a["aspect"] in ("quadratura", "oposição", "conjunção")
    ]

    return {
        "saturno_desorientado": {
            "detected": True,
            "intensity": "alta",
            "signature": f"Saturno em {saturn['sign']} casa {saturn['house']}",
            "indicators": [
                f"Saturno em {saturn['sign']} (signo de {saturn['element']}, modalidade {saturn['modality']}) — em queda no signo de Áries quebra o eixo de estrutura natural",
                f"Casa {saturn['house']} (parcerias) — autoridade buscada via outros, não internalizada",
                f"{len(saturn_hard_aspects)} aspectos tensos de Saturno detectados",
                "Saturno retrógrado — autoridade interna fragmentada, voz crítica desalinhada do tempo real",
            ],
            "shadow_pattern": "Cobrança difusa sem estrutura concreta. Sente-se 'atrasado' sem saber em quê. Procrastina e simultaneamente se pune por procrastinar.",
            "embodied_question": "Onde estou tentando provar valor para uma autoridade que nem existe mais?",
            "integration_path": "Construir um único compromisso pequeno e verificável por semana. Tornar Saturno tangível antes de espiritual.",
            "related_aspects": [f"{a['planet1']} {a['aspect']} {a['planet2']} (orb {a['orb']}°)" for a in saturn_hard_aspects[:3]],
        },
        "venus_negociada": {
            "detected": True,
            "intensity": "moderada-alta",
            "signature": f"Vênus em {venus['sign']} casa {venus['house']}",
            "indicators": [
                f"Vênus em {venus['sign']} — afetos intelectualizados, oscilação entre opções",
                f"Casa {venus['house']} (filosofia/expansão) — ama o que parece elevado, dispersa o que é íntimo",
                "Ascendente em Libra reforça padrão de agradar para evitar conflito",
                "Aspectos de Vênus com Mercúrio/Saturno indicam afeto condicionado a desempenho",
            ],
            "shadow_pattern": "Negocia desejo em troca de aprovação. Diz 'tudo bem' antes de saber se está bem. Confunde admiração com intimidade.",
            "embodied_question": "O que eu queria antes de aprender a perguntar o que o outro quer?",
            "integration_path": "Praticar o 'não' sem justificativa por 30 dias. Notar onde o corpo trava ao desejar diretamente.",
            "related_houses": [venus["house"], 1, 7],
        },
        "marte_apagado": {
            "detected": True,
            "intensity": "alta",
            "signature": f"Marte em {mars['sign']} casa {mars['house']}",
            "indicators": [
                f"Marte em {mars['sign']} — em queda, ação dissolvida em sensibilidade",
                f"Casa {mars['house']} (rotina/saúde) — energia gasta em manutenção, não em iniciativa",
                "Sem aspectos de fogo direto ao Marte — agressividade saudável bloqueada",
                "Padrão: cansaço crônico precede qualquer impulso de mudança",
            ],
            "shadow_pattern": "Raiva vira culpa antes de chegar à boca. Esforço sem direção. Adoece quando precisa confrontar.",
            "embodied_question": "Em qual situação eu aceitei calar para não parecer 'difícil'?",
            "integration_path": "Movimento físico sem objetivo estético — 20 min/dia. Treinar dizer o desconforto enquanto ele ainda é pequeno.",
            "somatic_markers": ["fadiga matinal", "tensão diafragmática", "sono não-reparador"],
        },
        "quiron_nao_integrado": {
            "detected": True,
            "intensity": "alta",
            "signature": f"Quíron em {chiron['sign']} casa {chiron['house']}",
            "indicators": [
                f"Quíron em {chiron['sign']} — ferida de identidade, 'quem eu sou se não estou cuidando?'",
                f"Casa {chiron['house']} (parcerias) — a ferida ativa nos vínculos íntimos",
                "Quíron conjunto Saturno (orb < 7°) — ferida fundida com cobrança parental",
                "Quíron retrógrado — processo de integração ainda em fase de reconhecimento",
            ],
            "shadow_pattern": "Cura os outros para não sentir o próprio corte. Atrai pessoas que repetem o desencontro original. Vergonha de pedir.",
            "embodied_question": "Que parte de mim eu trato como defeito quando é, na verdade, o lugar de onde eu enxergo melhor?",
            "integration_path": "Escrever a ferida em primeira pessoa, sem moral. Voltar ao texto em 30 dias e notar o que mudou de tom.",
            "core_wound_archetype": "O ferido que cura — mas que ainda não se deixou ser cuidado.",
        },
        "central_anchor": {
            "anchor_planet": "pluto",
            "anchor_position": f"Plutão em {pluto['sign']} casa {pluto['house']}",
            "anchor_signature": f"{pluto['degree_formatted']} {pluto['sign']} — domicílio",
            "anchor_archetype": "O Transformador Silencioso",
            "core_theme": "Poder pessoal através de transformação radical de recursos internos",
            "narrative": (
                "A âncora desta carta é Plutão em Escorpião na casa 2 — domicílio exato. "
                "Há um poder de regeneração profunda esperando ser ativado pelo reconhecimento "
                "do próprio valor (casa 2). Enquanto Saturno (Áries casa 7) tenta construir "
                "estrutura via aprovação alheia, Plutão sussurra que a estrutura real só vem "
                "quando o sujeito assume que possui — recursos, desejos, sombra. "
                "Os quatro pilares ANCORADA orbitam essa âncora: cada um deles é uma "
                "forma de adiar o encontro com Plutão."
            ),
            "activation_keys": [
                "Reconhecer onde já houve transformação concreta (não simbólica) na vida",
                "Mapear recursos próprios — financeiros, somáticos, relacionais — sem comparação",
                "Permitir que algo morra sem substituir imediatamente",
                "Notar quando 'eu não consigo' é, na verdade, 'eu não quero mais'",
            ],
            "diagnostic_priority_order": [
                "marte_apagado",
                "saturno_desorientado",
                "quiron_nao_integrado",
                "venus_negociada",
            ],
            "integration_horizon": "12 a 18 meses de trabalho consistente com retorno saturnino próximo de Áries",
        },
    }


# =============================================================================
# Endpoint principal
# =============================================================================
@app.post("/calculate-chart")
def calculate_chart(data: BirthData):
    # Resolução de localização (mock — substituir por geocoder real)
    resolved_location = {
        "city": data.birth_city,
        "state": data.birth_state,
        "country": data.birth_country,
        "latitude": -30.0346,
        "longitude": -51.2177,
        "timezone": "America/Sao_Paulo",
        "utc_offset": "-03:00",
        "resolved_at": datetime.utcnow().isoformat() + "Z",
        "source": "mock_geocoder",
    }

    natal_chart = build_natal_chart()
    houses = build_houses(NATAL_LONGITUDES["ascendant"])
    natal_aspects = build_natal_aspects()
    current_transits = build_current_transits()
    ancorada_extraction = build_ancorada_extraction(natal_chart, natal_aspects)

    chart_json = {
        "mode": "real",
        "is_mock": True,  # marcador honesto: dados são consistentes mas mockados
        "calculated_at": datetime.utcnow().isoformat() + "Z",
        "input_echo": {
            "birth_date": data.birth_date,
            "birth_time": data.birth_time,
            "birth_time_unknown": data.birth_time_unknown,
        },
        "natal_chart": natal_chart,
        "houses": houses,
        "natal_aspects": natal_aspects,
        "current_transits": current_transits,
        "ancorada_extraction": ancorada_extraction,
    }

    return {
        "resolved_location": resolved_location,
        "chart_json": chart_json,
    }


@app.get("/")
def root():
    return {
        "service": "ANCORADA Chart API",
        "version": "0.2.0",
        "endpoints": ["POST /calculate-chart"],
    }


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"}

from brujula.search import keywords, parse_intent, semantic_query

CITIES = ["Barranco", "Miraflores", "San Isidro", "Santiago de Surco", "Trujillo", "José Luis Bustamante"]
TODAY = "2026-10-12 10:00"


def test_days_and_time_of_day():
    i = parse_intent("Quiero ir el jueves por la noche", CITIES, TODAY)
    assert i["days"] == ["2026-10-15"] and i["time"] == "noche"


def test_morning_phrase_is_not_tomorrow():
    i = parse_intent("prefiero ir por la mañana", CITIES, TODAY)
    assert i["time"] == "mañana" and i["days"] == []


def test_tomorrow_and_weekend():
    assert parse_intent("mañana", CITIES, TODAY)["days"] == ["2026-10-13"]
    assert parse_intent("el fin de semana", CITIES, TODAY)["days"] == ["2026-10-17", "2026-10-18"]


def test_city_alias_mode_and_top_n():
    i = parse_intent("Vivo en Surco, solo presencial, dame el top 3", CITIES, TODAY)
    assert i["city"] == "Santiago de Surco" and i["mode"] == "presencial" and i["top_n"] == 3


def test_goals():
    g = parse_intent("quiero aprender, conocer gente y levantar capital", CITIES, TODAY)["goals"]
    assert {"aprender", "networking", "inversion"} <= set(g)


def test_semantic_query_drops_logistics():
    q = semantic_query("Quiero aprender sobre agentes de IA. Vivo en Surco, prefiero presencial y por las tardes.", CITIES)
    assert "surco" not in q and "presencial" not in q and "tardes" not in q and "agentes" in q


def test_keywords_skip_stopwords():
    assert "agentes" in keywords("quiero aprender agentes") and "quiero" not in keywords("quiero aprender agentes")


def test_solo_virtual_is_hard_filter_but_prefiero_is_not():
    assert parse_intent("quiero algo solo virtual", CITIES, TODAY)["mode_hard"] is True
    assert parse_intent("prefiero presencial", CITIES, TODAY)["mode_hard"] is False

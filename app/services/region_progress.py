"""Progresso visual das dez caixas fixas da bancada, por rodada."""

from core.classifier import (
    MACROREGION_DESTINATIONS,
    STATE_DESTINATIONS,
    STATE_TO_MACROREGION,
    MacroRegion,
)


REGION_NAMES = {
    MacroRegion.NORTH: "Norte",
    MacroRegion.SOUTH: "Sul",
    MacroRegion.SOUTHEAST: "Sudeste",
    MacroRegion.NORTHEAST: "Nordeste",
    MacroRegion.CENTRAL_WEST: "Centro-Oeste",
}

STATE_NAMES = {
    "RO": "Rondônia", "AM": "Amazonas", "SC": "Santa Catarina",
    "PR": "Paraná", "SP": "São Paulo", "MG": "Minas Gerais",
    "BA": "Bahia", "PE": "Pernambuco", "MT": "Mato Grosso", "GO": "Goiás",
}


def get_region_progress(repository) -> dict:
    deliveries, started_at = repository.region_progress_deliveries()
    regions = []
    for number, region in enumerate(MacroRegion, start=1):
        states = []
        for destination in MACROREGION_DESTINATIONS[region]:
            state = next(
                state for state, fixed_destination in STATE_DESTINATIONS.items()
                if fixed_destination == destination and STATE_TO_MACROREGION[state] == region
            )
            delivery = deliveries.get((state, destination), {})
            states.append({
                "uf": state,
                "nome": STATE_NAMES[state],
                "destino": destination,
                "entregas": delivery.get("total", 0),
                "ultima_entrega": delivery.get("ultima_entrega"),
                "concluido": delivery.get("total", 0) > 0,
            })
        completed = sum(state["concluido"] for state in states)
        regions.append({
            "numero": number,
            "codigo": region.value,
            "nome": REGION_NAMES[region],
            "entregues": completed,
            "total": len(states),
            "concluida": completed == len(states),
            "estados": states,
        })
    return {
        "rodada_iniciada_em": started_at,
        "regioes": regions,
        "regioes_completas": sum(region["concluida"] for region in regions),
        "total_regioes": len(regions),
        "estados_entregues": sum(region["entregues"] for region in regions),
        "total_estados": sum(region["total"] for region in regions),
    }

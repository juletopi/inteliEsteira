"""Valida o QR Code e resolve o destino fisico de um produto.

Contrato do QR Code::

    {"produto_id": "PROD-0087"}

O QR identifica somente o produto. A UF vem do cadastro persistente, evitando
que o destino seja definido ou adulterado no proprio QR Code.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from enum import Enum
import json
import re


class MacroRegion(str, Enum):
    NORTH = "NORTE"
    SOUTH = "SUL"
    SOUTHEAST = "SUDESTE"
    NORTHEAST = "NORDESTE"
    CENTRAL_WEST = "CENTRO_OESTE"


STATE_TO_MACROREGION = {
    "AC": MacroRegion.NORTH,
    "AP": MacroRegion.NORTH,
    "AM": MacroRegion.NORTH,
    "PA": MacroRegion.NORTH,
    "RO": MacroRegion.NORTH,
    "RR": MacroRegion.NORTH,
    "TO": MacroRegion.NORTH,
    "PR": MacroRegion.SOUTH,
    "RS": MacroRegion.SOUTH,
    "SC": MacroRegion.SOUTH,
    "ES": MacroRegion.SOUTHEAST,
    "MG": MacroRegion.SOUTHEAST,
    "RJ": MacroRegion.SOUTHEAST,
    "SP": MacroRegion.SOUTHEAST,
    "AL": MacroRegion.NORTHEAST,
    "BA": MacroRegion.NORTHEAST,
    "CE": MacroRegion.NORTHEAST,
    "MA": MacroRegion.NORTHEAST,
    "PB": MacroRegion.NORTHEAST,
    "PE": MacroRegion.NORTHEAST,
    "PI": MacroRegion.NORTHEAST,
    "RN": MacroRegion.NORTHEAST,
    "SE": MacroRegion.NORTHEAST,
    "DF": MacroRegion.CENTRAL_WEST,
    "GO": MacroRegion.CENTRAL_WEST,
    "MT": MacroRegion.CENTRAL_WEST,
    "MS": MacroRegion.CENTRAL_WEST,
}


MACROREGION_DESTINATIONS = {
    MacroRegion.NORTH: ("R01", "R02"),
    MacroRegion.SOUTH: ("R03", "R04"),
    MacroRegion.SOUTHEAST: ("R05", "R06"),
    MacroRegion.NORTHEAST: ("R07", "R08"),
    MacroRegion.CENTRAL_WEST: ("R09", "R10"),
}


PRODUCT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
MAX_QR_CODE_LENGTH = 512


class ClassificationError(ValueError):
    """Erro de dominio que pode ser devolvido de forma segura pela API."""

    code = "CLASSIFICATION_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidQRCodeError(ClassificationError):
    code = "INVALID_QR_CODE"


class UnknownStateError(ClassificationError):
    code = "UNKNOWN_STATE"


class ProductNotFoundError(ClassificationError):
    code = "PRODUCT_NOT_FOUND"


class ProductInactiveError(ClassificationError):
    code = "PRODUCT_INACTIVE"


class DestinationUnavailableError(ClassificationError):
    code = "DESTINATION_UNAVAILABLE"


@dataclass(frozen=True)
class Product:
    product_id: str
    state: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.product_id,
            "uf": self.state,
        }


@dataclass(frozen=True)
class RouteDecision:
    product: Product
    macroregion: MacroRegion
    destination: str
    candidates: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "produto": self.product.as_dict(),
            "macroregiao": self.macroregion.value,
            "destino": self.destination,
            "candidatos": list(self.candidates),
        }


def _read_alias(payload: Mapping[str, object], names: tuple[str, ...], label: str) -> object:
    present = [(name, payload[name]) for name in names if name in payload]
    if not present:
        raise InvalidQRCodeError(f"Campo obrigatorio ausente: {label}.")

    values = {str(value).strip() for _, value in present}
    if len(values) > 1:
        raise InvalidQRCodeError(f"Campos conflitantes para {label}.")

    return present[0][1]


def validate_product_id(raw_product_id: object) -> str:
    if not isinstance(raw_product_id, str):
        raise InvalidQRCodeError("O campo produto_id deve ser uma string.")
    product_id = raw_product_id.strip()
    if not PRODUCT_ID_PATTERN.fullmatch(product_id):
        raise InvalidQRCodeError(
            "O produto_id deve ter de 1 a 64 caracteres alfanumericos "
            "e pode conter ponto, hifen, sublinhado ou dois-pontos."
        )
    return product_id


def validate_state(raw_state: object) -> str:
    if not isinstance(raw_state, str):
        raise InvalidQRCodeError("O campo uf deve ser uma string.")
    state = raw_state.strip().upper()
    if state not in STATE_TO_MACROREGION:
        raise UnknownStateError(f"UF desconhecida ou nao suportada: {state or '<vazia>'}.")
    return state


def read_product_id(qr_code: str) -> str:
    """Extrai e valida o identificador presente no QR Code."""

    if not isinstance(qr_code, str):
        raise InvalidQRCodeError("O QR Code deve ser uma string.")

    qr_code = qr_code.strip()
    if not qr_code:
        raise InvalidQRCodeError("O QR Code esta vazio.")
    if len(qr_code) > MAX_QR_CODE_LENGTH:
        raise InvalidQRCodeError("O QR Code excede o tamanho permitido.")

    try:
        payload = json.loads(qr_code)
    except json.JSONDecodeError as exc:
        raise InvalidQRCodeError("O QR Code nao contem um JSON valido.") from exc

    if not isinstance(payload, dict):
        raise InvalidQRCodeError("O conteudo do QR Code deve ser um objeto JSON.")

    raw_product_id = _read_alias(payload, ("produto_id", "product_id"), "produto_id")
    return validate_product_id(raw_product_id)


def identify_product(
    qr_code: str,
    product_resolver: Callable[[str], Mapping[str, object] | Product | None],
) -> Product:
    """Consulta o cadastro e devolve o produto associado ao QR Code."""

    product_id = read_product_id(qr_code)
    registered_product = product_resolver(product_id)
    if registered_product is None:
        raise ProductNotFoundError(f"Produto nao cadastrado: {product_id}.")

    if isinstance(registered_product, Product):
        return registered_product
    if not isinstance(registered_product, Mapping):
        raise ClassificationError("O cadastro retornou um produto invalido.")

    if registered_product.get("ativo") is False:
        raise ProductInactiveError(f"Produto inativo: {product_id}.")

    state = validate_state(
        registered_product.get("uf", registered_product.get("state"))
    )
    registered_product_id = validate_product_id(
        registered_product.get("id", product_id)
    )

    return Product(product_id=registered_product_id, state=state)


def determine_destination(
    product: Product,
    occupancy: Mapping[str, int] | None = None,
    unavailable: Collection[str] | None = None,
) -> RouteDecision:
    """Escolhe a saida disponivel com menor ocupacao para o produto."""

    if not isinstance(product, Product):
        raise TypeError("product deve ser uma instancia de Product.")

    try:
        macroregion = STATE_TO_MACROREGION[product.state]
    except KeyError as exc:
        raise UnknownStateError(
            f"UF desconhecida ou nao suportada: {product.state or '<vazia>'}."
        ) from exc

    if occupancy is not None and not isinstance(occupancy, Mapping):
        raise ClassificationError("A ocupacao deve ser um mapeamento de destinos.")
    if unavailable is not None and (
        isinstance(unavailable, str) or not isinstance(unavailable, Collection)
    ):
        raise ClassificationError("Os destinos indisponiveis devem formar uma colecao.")

    candidates = MACROREGION_DESTINATIONS[macroregion]
    unavailable_set = {
        destination.strip().upper()
        for destination in (unavailable or ())
        if isinstance(destination, str)
    }
    available = tuple(
        destination for destination in candidates if destination not in unavailable_set
    )

    if not available:
        raise DestinationUnavailableError(
            f"Nao ha destino disponivel para a macrorregiao {macroregion.value}."
        )

    normalized_occupancy: dict[str, int] = {}
    for destination, quantity in (occupancy or {}).items():
        normalized_destination = str(destination).strip().upper()
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise ClassificationError(
                f"Ocupacao invalida para {normalized_destination or '<destino>'}."
            )
        normalized_occupancy[normalized_destination] = quantity

    destination = min(
        available,
        key=lambda candidate: (normalized_occupancy.get(candidate, 0), candidates.index(candidate)),
    )

    return RouteDecision(
        product=product,
        macroregion=macroregion,
        destination=destination,
        candidates=candidates,
    )


def classify_qr_code(
    qr_code: str,
    product_resolver: Callable[[str], Mapping[str, object] | Product | None],
    occupancy: Mapping[str, int] | None = None,
    unavailable: Collection[str] | None = None,
) -> RouteDecision:
    """Executa a validacao do QR e a resolucao completa da rota."""

    product = identify_product(qr_code, product_resolver)
    return determine_destination(product, occupancy=occupancy, unavailable=unavailable)

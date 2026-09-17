import json
import unittest

from core.classifier import (
    DestinationUnavailableError,
    InvalidQRCodeError,
    MACROREGION_DESTINATIONS,
    MacroRegion,
    ProductInactiveError,
    ProductNotFoundError,
    STATE_TO_MACROREGION,
    UnknownStateError,
    classify_qr_code,
    identify_product,
)


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.products = {
            "PROD-1": {"id": "PROD-1", "uf": "CE", "ativo": True},
            "PROD-0087": {"id": "PROD-0087", "uf": "CE", "ativo": True},
            "PRODUCT:1": {"id": "PRODUCT:1", "uf": "SP", "ativo": True},
        }

    def resolve(self, product_id):
        return self.products.get(product_id)

    def set_product_state(self, state):
        self.products["PROD-1"] = {
            "id": "PROD-1",
            "uf": state,
            "ativo": True,
        }

    @staticmethod
    def qr(product_id="PROD-1"):
        return json.dumps({"produto_id": product_id})

    def test_all_brazilian_states_are_mapped(self):
        self.assertEqual(len(STATE_TO_MACROREGION), 27)
        self.assertEqual(STATE_TO_MACROREGION["CE"], MacroRegion.NORTHEAST)
        self.assertEqual(STATE_TO_MACROREGION["SP"], MacroRegion.SOUTHEAST)
        self.assertEqual(STATE_TO_MACROREGION["DF"], MacroRegion.CENTRAL_WEST)

    def test_ten_physical_destinations_are_unique(self):
        destinations = [
            destination
            for pair in MACROREGION_DESTINATIONS.values()
            for destination in pair
        ]
        self.assertEqual(len(destinations), 10)
        self.assertEqual(len(set(destinations)), 10)
        self.assertEqual(destinations, [f"R{index:02d}" for index in range(1, 11)])

    def test_identifies_product_from_registry(self):
        product = identify_product(self.qr("PROD-0087"), self.resolve)
        self.assertEqual(product.product_id, "PROD-0087")
        self.assertEqual(product.state, "CE")

    def test_accepts_english_product_id_alias(self):
        product = identify_product(
            json.dumps({"product_id": "PRODUCT:1"}),
            self.resolve,
        )
        self.assertEqual(product.product_id, "PRODUCT:1")
        self.assertEqual(product.state, "SP")

    def test_rejects_invalid_json(self):
        with self.assertRaises(InvalidQRCodeError):
            identify_product("PROD-0087", self.resolve)

    def test_rejects_missing_product_id(self):
        with self.assertRaises(InvalidQRCodeError):
            identify_product(json.dumps({"uf": "CE"}), self.resolve)

    def test_rejects_unknown_product(self):
        with self.assertRaises(ProductNotFoundError):
            identify_product(self.qr("UNKNOWN"), self.resolve)

    def test_rejects_inactive_product(self):
        self.products["PROD-1"]["ativo"] = False
        with self.assertRaises(ProductInactiveError):
            identify_product(self.qr(), self.resolve)

    def test_rejects_invalid_registered_state(self):
        self.set_product_state("XX")
        with self.assertRaises(UnknownStateError):
            identify_product(self.qr(), self.resolve)

    def test_selects_least_occupied_destination(self):
        decision = classify_qr_code(
            self.qr(),
            self.resolve,
            occupancy={"R07": 4, "R08": 1},
        )
        self.assertEqual(decision.macroregion, MacroRegion.NORTHEAST)
        self.assertEqual(decision.destination, "R08")

    def test_uses_deterministic_first_destination_on_tie(self):
        self.set_product_state("PR")
        decision = classify_qr_code(
            self.qr(),
            self.resolve,
            occupancy={"R03": 0, "R04": 0},
        )
        self.assertEqual(decision.destination, "R03")

    def test_skips_unavailable_destination(self):
        self.set_product_state("RO")
        decision = classify_qr_code(
            self.qr(),
            self.resolve,
            unavailable=["R01"],
        )
        self.assertEqual(decision.destination, "R02")

    def test_fails_when_both_destinations_are_unavailable(self):
        self.set_product_state("MG")
        with self.assertRaises(DestinationUnavailableError):
            classify_qr_code(
                self.qr(),
                self.resolve,
                unavailable=["R05", "R06"],
            )


if __name__ == "__main__":
    unittest.main()

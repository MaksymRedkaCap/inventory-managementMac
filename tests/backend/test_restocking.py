"""
Tests for restocking orders and the cost/lead-time fields on demand forecasts.
"""
import pytest


def _forecasts_by_sku(client):
    return {f["item_sku"]: f for f in client.get("/api/demand").json()}


class TestDemandForecastCostFields:
    """Restocking depends on every forecast carrying a cost and lead time."""

    def test_forecasts_have_cost_and_lead_time(self, client):
        data = client.get("/api/demand").json()
        assert len(data) > 0
        for forecast in data:
            assert forecast["unit_cost"] > 0
            assert forecast["lead_time_days"] > 0


class TestRestockingOrders:
    """Test suite for POST/GET /api/restocking-orders."""

    # The order store is module-level state shared across tests (it is never reset),
    # so these tests compare against the count before they act instead of assuming
    # an empty list.

    def test_create_order_computes_total_and_max_lead_time(self, client):
        forecasts = _forecasts_by_sku(client)
        # Pick the two items with the shortest and longest lead times
        ordered = sorted(forecasts.values(), key=lambda f: f["lead_time_days"])
        fast, slow = ordered[0], ordered[-1]

        payload = {"items": [
            {"sku": fast["item_sku"], "quantity": 10},
            {"sku": slow["item_sku"], "quantity": 2},
        ]}
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        expected_total = round(10 * fast["unit_cost"] + 2 * slow["unit_cost"], 2)
        assert order["total_cost"] == expected_total
        assert order["lead_time_days"] == slow["lead_time_days"]
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == 2
        assert order["submitted_date"] < order["expected_delivery"]

    def test_list_returns_newest_first(self, client):
        sku = next(iter(_forecasts_by_sku(client)))
        first = client.post("/api/restocking-orders", json={"items": [{"sku": sku, "quantity": 1}]}).json()
        second = client.post("/api/restocking-orders", json={"items": [{"sku": sku, "quantity": 2}]}).json()

        listed = client.get("/api/restocking-orders").json()
        ids = [o["id"] for o in listed]
        assert ids.index(second["id"]) < ids.index(first["id"])

    def test_empty_order_rejected(self, client):
        response = client.post("/api/restocking-orders", json={"items": []})
        assert response.status_code == 400

    def test_unknown_sku_rejected(self, client):
        response = client.post("/api/restocking-orders", json={"items": [{"sku": "NOPE-000", "quantity": 1}]})
        assert response.status_code == 400
        assert "NOPE-000" in response.json()["detail"]

    @pytest.mark.parametrize("quantity", [0, -5])
    def test_non_positive_quantity_rejected(self, client, quantity):
        sku = next(iter(_forecasts_by_sku(client)))
        response = client.post("/api/restocking-orders", json={"items": [{"sku": sku, "quantity": quantity}]})
        assert response.status_code == 400

    def test_rejected_order_is_not_stored(self, client):
        before = len(client.get("/api/restocking-orders").json())
        client.post("/api/restocking-orders", json={"items": [{"sku": "NOPE-000", "quantity": 1}]})
        assert len(client.get("/api/restocking-orders").json()) == before

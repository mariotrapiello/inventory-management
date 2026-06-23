"""
Tests for restocking recommendation and order submission endpoints.
"""
import re
from datetime import datetime

import pytest


class TestRestockingRecommendations:
    """Test suite for the restocking recommendations endpoint."""

    def test_get_recommendations_returns_200(self, client):
        """Test getting recommendations for a typical budget."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        assert response.status_code == 200

    def test_recommendations_response_structure(self, client):
        """Test the top-level response shape and per-item fields."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()

        assert "budget" in data
        assert "total_recommended_cost" in data
        assert "remaining_budget" in data
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)
        assert len(data["recommendations"]) > 0

        first_item = data["recommendations"][0]
        for field in [
            "item_sku", "item_name", "current_demand", "forecasted_demand",
            "quantity_on_hand", "trend", "restock_quantity", "unit_cost",
            "restock_cost", "recommended", "has_inventory_match"
        ]:
            assert field in first_item

    def test_zero_budget_recommends_nothing(self, client):
        """Test that a budget of 0 results in no recommended items."""
        response = client.get("/api/restocking/recommendations?budget=0")
        data = response.json()

        assert all(not item["recommended"] for item in data["recommendations"])
        assert data["total_recommended_cost"] == 0
        assert data["remaining_budget"] == 0

    def test_large_budget_recommends_all_eligible_items(self, client):
        """Test that a very large budget recommends every restockable item."""
        response = client.get("/api/restocking/recommendations?budget=200000")
        data = response.json()

        eligible = [
            item for item in data["recommendations"]
            if item["has_inventory_match"] and item["restock_quantity"] > 0
        ]
        assert len(eligible) > 0
        assert all(item["recommended"] for item in eligible)

    def test_urgency_ordering_increasing_trend_first(self, client):
        """Test that increasing-trend items are prioritized for a small fitting budget."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()

        recommended = [item for item in data["recommendations"] if item["recommended"]]
        increasing_recommended = [item for item in recommended if item["trend"] == "increasing"]
        non_increasing_recommended = [item for item in recommended if item["trend"] != "increasing"]

        assert len(increasing_recommended) > 0
        # Every increasing-trend item that was recommended should be cheaper to
        # justify being skipped only if a non-increasing item also fits - here we
        # just confirm all increasing-trend eligible items got recommended before
        # budget exhausted on non-increasing ones.
        eligible_increasing = [
            item for item in data["recommendations"]
            if item["trend"] == "increasing" and item["has_inventory_match"] and item["restock_quantity"] > 0
        ]
        assert all(item["recommended"] for item in eligible_increasing) or len(non_increasing_recommended) == 0

    def test_greedy_fill_never_exceeds_budget(self, client):
        """Test that recommended cost never exceeds the requested budget across several budgets."""
        for budget in [0, 1000, 5000, 15000, 50000, 100000, 200000]:
            response = client.get(f"/api/restocking/recommendations?budget={budget}")
            data = response.json()
            assert data["total_recommended_cost"] <= budget

    def test_items_without_inventory_match_excluded_from_recommendations(self, client):
        """Test that demand-forecast items always resolve to an inventory match after the data fix."""
        response = client.get("/api/restocking/recommendations?budget=200000")
        data = response.json()

        assert all(item["has_inventory_match"] for item in data["recommendations"])

    def test_items_with_demand_already_met_marked_not_recommended(self, client):
        """Test that items needing zero restock quantity are never recommended."""
        response = client.get("/api/restocking/recommendations?budget=200000")
        data = response.json()

        zero_restock_items = [item for item in data["recommendations"] if item["restock_quantity"] == 0]
        assert len(zero_restock_items) > 0
        assert all(not item["recommended"] for item in zero_restock_items)


class TestRestockingOrderSubmission:
    """Test suite for submitting a restocking order."""

    def test_create_restocking_order_success(self, client):
        """Test successfully creating a restocking order."""
        payload = {
            "items": [
                {"item_sku": "PSU-501", "item_name": "5V 10A Switching Power Supply", "quantity": 10, "unit_cost": 18.99}
            ],
            "budget": 50000
        }
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["source"] == "restocking"
        assert data["lead_time_days"] == 14
        assert data["status"] == "Processing"
        assert data["customer"] == "Internal Restocking"

    def test_order_expected_delivery_is_14_days_after_order_date(self, client):
        """Test that expected_delivery is exactly 14 days after order_date."""
        payload = {
            "items": [
                {"item_sku": "WDG-001", "item_name": "Industrial Widget Type A", "quantity": 5, "unit_cost": 35.0}
            ],
            "budget": 10000
        }
        response = client.post("/api/restocking/orders", json=payload)
        data = response.json()

        order_date = datetime.fromisoformat(data["order_date"])
        expected_delivery = datetime.fromisoformat(data["expected_delivery"])
        assert (expected_delivery - order_date).days == 14

    def test_order_number_follows_existing_sequence_format(self, client):
        """Test that the generated order_number matches the ORD-2025-#### pattern."""
        before_response = client.get("/api/orders")
        before_orders = before_response.json()
        max_id_before = max(int(order["id"]) for order in before_orders)

        payload = {
            "items": [
                {"item_sku": "GSK-203", "item_name": "High-Temperature Gasket", "quantity": 20, "unit_cost": 8.75}
            ],
            "budget": 5000
        }
        response = client.post("/api/restocking/orders", json=payload)
        data = response.json()

        assert re.match(r"^ORD-2025-\d{4}$", data["order_number"])
        assert int(data["id"]) > max_id_before

    def test_submitted_order_appears_in_get_orders(self, client):
        """Test that a newly submitted restocking order is visible via GET /api/orders."""
        payload = {
            "items": [
                {"item_sku": "VLV-506", "item_name": "Pressure Relief Valve", "quantity": 5, "unit_cost": 65.0}
            ],
            "budget": 5000
        }
        post_response = client.post("/api/restocking/orders", json=payload)
        created_order_number = post_response.json()["order_number"]

        get_response = client.get("/api/orders")
        all_order_numbers = [order["order_number"] for order in get_response.json()]
        assert created_order_number in all_order_numbers

    def test_create_restocking_order_rejects_empty_items(self, client):
        """Test that submitting an order with no items returns a 400 error."""
        response = client.post("/api/restocking/orders", json={"items": [], "budget": 1000})
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data

    def test_total_value_matches_sum_of_item_costs(self, client):
        """Test that total_value is correctly calculated from submitted items."""
        payload = {
            "items": [
                {"item_sku": "BRG-102", "item_name": "Steel Bearing Assembly", "quantity": 8, "unit_cost": 22.5},
                {"item_sku": "CTL-330", "item_name": "Logic Controller Board", "quantity": 3, "unit_cost": 45.0}
            ],
            "budget": 5000
        }
        response = client.post("/api/restocking/orders", json=payload)
        data = response.json()

        expected_total = sum(item["quantity"] * item["unit_cost"] for item in payload["items"])
        assert abs(data["total_value"] - expected_total) < 0.01

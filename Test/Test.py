import pytest
import project

# ================= Test 1 =================

@pytest.fixture
def mock_names(monkeypatch):
    names = {
        "1": "Ali",
        "2": "Sara",
        "3": "Reza",
    }
    monkeypatch.setattr(project, "get_name_by_id", lambda m_id: names[m_id])

@pytest.mark.parametrize(
    "selected_ids, expenses, expected",
    [
        # ===== group expense =====
        (
            ["1", "2", "3"],
            [{
                "description": "Dinner",
                "type": "group",
                "amount": 300,
                "payer_id": "1",
                "participants": ["1", "2", "3"]
            }],
            {
                "Ali": 200,
                "Sara": -100,
                "Reza": -100
            }
        ),

        # ===== individual expense =====
        (
            ["1", "2"],
            [{
                "description": "Lunch",
                "type": "individual",
                "amount": 200,
                "payer_id": "1",
                "individual_amounts": {
                    "1": 50,
                    "2": 150
                }
            }],
            {
                "Ali": 150,
                "Sara": -150
            }
        ),
    ]
)
def test_calculate_final_balances(mock_names, selected_ids, expenses, expected):
    balances, report, plan = project.calculate_final_balances(selected_ids, expenses)
    assert balances == expected


# ================= Test 2 =================

def test_search_ddgs(monkeypatch):
    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def text(self, topic, max_results=3):
            return [{
                "title": "Test Title",
                "href": "http://test.ir",
                "body": "Testing"
            }]

    monkeypatch.setattr(project, "DDGS", lambda: FakeDDGS())

    result = project.search_ddgs("Iran")

    assert "Test Title" in result
    assert "http://test.ir" in result
    assert "Testing" in result

# ================= Test 3 =================

def test_summarize_text():
    result = project.summarize_text("any input text")
    assert result == "summary_of_text_here"
